# Stage Environment Terraform Configuration for EstateOS / HRrealestate

locals {
  backend_image  = var.backend_container_image != "" ? var.backend_container_image : "${data.aws_ecr_repository.backend.repository_url}:stage"
  frontend_image = var.frontend_container_image != "" ? var.frontend_container_image : ""
}

# --- 1. Dedicated Stage VPC Module ---
module "vpc" {
  source = "../../modules/vpc"

  aws_region   = var.aws_region
  project_name = var.project_name
  environment  = "stage"
  vpc_cidr     = var.vpc_cidr

  public_subnet_a_cidr     = var.public_subnet_a_cidr
  public_subnet_b_cidr     = var.public_subnet_b_cidr
  private_db_subnet_a_cidr = var.private_db_subnet_a_cidr
  private_db_subnet_b_cidr = var.private_db_subnet_b_cidr
}

# --- 2. Security Groups Module ---
module "security_groups" {
  source = "../../modules/security_groups"

  project_name  = var.project_name
  environment   = "stage"
  vpc_id        = module.vpc.vpc_id
  app_port      = var.app_port
  frontend_port = var.frontend_port
}

# --- 3. S3 Project Storage Module ---
module "s3" {
  source = "../../modules/s3"

  project_name      = var.project_name
  environment       = "stage"
  aws_account_id    = var.aws_account_id
  enable_versioning = true
  force_destroy     = false
}

# --- 4. RDS PostgreSQL 16 Module ---
module "rds" {
  source = "../../modules/rds"

  project_name          = var.project_name
  environment           = "stage"
  database_subnet_ids   = module.vpc.private_db_subnet_ids
  rds_security_group_id = module.security_groups.rds_security_group_id

  engine_version        = var.db_engine_version
  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  db_name               = var.db_name
  db_username           = var.db_username
  deletion_protection     = false
  skip_final_snapshot     = true
  multi_az                = false
  backup_retention_period = 1
}

# --- 5. Application Secrets Manager Module ---
module "secrets" {
  source = "../../modules/secrets"

  project_name            = var.project_name
  environment             = "stage"
  recovery_window_in_days = 0
}

# --- 6. ECR Repositories Data Source (Shared with prod in same AWS account) ---
data "aws_ecr_repository" "backend" {
  name = "${var.project_name}/backend"
}

# --- 7. IAM Roles Module ---
module "iam" {
  source = "../../modules/iam"

  aws_region                 = var.aws_region
  aws_account_id             = var.aws_account_id
  project_name               = var.project_name
  environment                = "stage"
  github_repository          = var.github_repository
  s3_bucket_arn              = module.s3.bucket_arn
  enable_github_actions_role = var.enable_github_actions_role
}

# --- 8. Application Load Balancer Module ---
module "alb" {
  source = "../../modules/alb"

  project_name          = var.project_name
  environment           = "stage"
  vpc_id                = module.vpc.vpc_id
  public_subnet_ids     = module.vpc.public_subnet_ids
  alb_security_group_id = module.security_groups.alb_security_group_id
  app_port              = var.app_port
  health_check_path     = "/health/ready"
  certificate_arn       = var.certificate_arn

  enable_frontend      = var.enable_frontend
  frontend_port        = var.frontend_port
  frontend_host_header = var.frontend_host_header
  api_host_header      = var.api_host_header
}

# --- 9. ECS Fargate Cluster & Services Module ---
module "ecs" {
  source = "../../modules/ecs"

  aws_region                = var.aws_region
  project_name              = var.project_name
  environment               = "stage"
  subnet_ids                = module.vpc.public_subnet_ids
  ecs_security_group_id     = module.security_groups.ecs_security_group_id
  execution_role_arn        = module.iam.execution_role_arn
  task_role_arn             = module.iam.task_role_arn
  api_target_group_arn      = module.alb.api_target_group_arn
  frontend_target_group_arn = var.enable_frontend ? module.alb.frontend_target_group_arn : null
  backend_container_image   = local.backend_image
  frontend_container_image  = local.frontend_image
  app_port                  = var.app_port
  frontend_port             = var.frontend_port
  api_cpu                   = var.api_cpu
  api_memory                = var.api_memory
  worker_cpu                = var.worker_cpu
  worker_memory             = var.worker_memory
  frontend_cpu              = var.frontend_cpu
  frontend_memory           = var.frontend_memory
  api_desired_count         = var.api_desired_count
  worker_desired_count      = var.worker_desired_count
  frontend_desired_count    = var.frontend_desired_count
  enable_frontend           = var.enable_frontend
  assign_public_ip          = true
  log_retention_days        = 14
  enable_container_insights = false

  backend_environment_variables = [
    { name = "ENV", value = "dev" },
    { name = "API_PORT", value = tostring(var.app_port) },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = module.s3.bucket_id },
    { name = "S3_REGION", value = var.aws_region },
    { name = "FRONTEND_BASE_URL", value = var.frontend_base_url },
    { name = "GOOGLE_LOGIN_REDIRECT_URI", value = var.google_login_redirect_uri },
    { name = "GOOGLE_OAUTH_REDIRECT_URI", value = "https://${var.api_host_header}/api/auth/google/callback" },
    { name = "DASHBOARD_CORS_ORIGINS", value = var.dashboard_cors_origins },
    { name = "DASHBOARD_AUTH_PROVIDER", value = "google" },
    { name = "DASHBOARD_TRUST_FORWARDED_FOR", value = "true" },
    { name = "LLM_MODEL", value = "google-gla:gemini-2.5-flash" },
    { name = "EMBEDDING_MODEL", value = "google-gla:gemini-embedding-001" },
    # google-genai 3.x defaults to API v1, which rejects instructions/tools; the code pins v1beta too.
    { name = "GOOGLE_GENAI_API_VERSION", value = "v1beta" },
    { name = "LLM_TIMEOUT_SEC", value = "30" },
    # Tried when Gemini answers an error; skipped while OPENAI_API_KEY is empty (app/llm/runtime.py).
    { name = "LLM_FALLBACK_MODELS", value = "openai:gpt-4.1-mini" },
    { name = "WHATSAPP_PROVIDER", value = "cloud_api" },
    { name = "WHATSAPP_API_BASE_URL", value = "https://graph.facebook.com/v23.0" },
    { name = "WHATSAPP_FROM_NUMBER", value = "916364840587" },
    { name = "OWNER_PHONE_NUMBER", value = "916364840587" },
    { name = "OWNER_TEMPLATE_NAME", value = "estateos_pending" },
    { name = "OWNER_TEMPLATE_LANGUAGE", value = "en" },
    { name = "GMAIL_PROVIDER", value = "google" },
    { name = "CALENDAR_PROVIDER", value = "google" },
    { name = "DRIVE_PROVIDER", value = "google" },
    { name = "TENANT_SENDS_PER_HOUR", value = "30" },
    # BRIXX Data API mirror (live on stage since 2026-11-15; prod has no BRIXX_TOKEN yet).
    { name = "BRIXX_PROVIDER", value = "api" },
    { name = "BRIXX_AUTH_SCHEME", value = "bearer" }
  ]

  backend_secrets = [
    { name = "DATABASE_URL", valueFrom = "${module.secrets.secret_arn}:DATABASE_URL::" },
    { name = "OPENAI_API_KEY", valueFrom = "${module.secrets.secret_arn}:OPENAI_API_KEY::" },
    { name = "GEMINI_API_KEY", valueFrom = "${module.secrets.secret_arn}:GEMINI_API_KEY::" },
    { name = "GROQ_API_KEY", valueFrom = "${module.secrets.secret_arn}:GROQ_API_KEY::" },
    { name = "SENTRY_DSN", valueFrom = "${module.secrets.secret_arn}:SENTRY_DSN::" },
    { name = "LANGFUSE_PUBLIC_KEY", valueFrom = "${module.secrets.secret_arn}:LANGFUSE_PUBLIC_KEY::" },
    { name = "LANGFUSE_SECRET_KEY", valueFrom = "${module.secrets.secret_arn}:LANGFUSE_SECRET_KEY::" },
    { name = "DASHBOARD_SESSION_SECRET", valueFrom = "${module.secrets.secret_arn}:DASHBOARD_SESSION_SECRET::" },
    { name = "GOOGLE_OAUTH_CLIENT_ID", valueFrom = "${module.secrets.secret_arn}:GOOGLE_OAUTH_CLIENT_ID::" },
    { name = "GOOGLE_OAUTH_CLIENT_SECRET", valueFrom = "${module.secrets.secret_arn}:GOOGLE_OAUTH_CLIENT_SECRET::" },
    { name = "WHATSAPP_ACCESS_TOKEN", valueFrom = "${module.secrets.secret_arn}:WHATSAPP_ACCESS_TOKEN::" },
    { name = "WHATSAPP_PHONE_NUMBER_ID", valueFrom = "${module.secrets.secret_arn}:WHATSAPP_PHONE_NUMBER_ID::" },
    { name = "WHATSAPP_APP_SECRET", valueFrom = "${module.secrets.secret_arn}:WHATSAPP_APP_SECRET::" },
    { name = "WHATSAPP_VERIFY_TOKEN", valueFrom = "${module.secrets.secret_arn}:WHATSAPP_VERIFY_TOKEN::" },
    { name = "BRIXX_TOKEN", valueFrom = "${module.secrets.secret_arn}:BRIXX_TOKEN::" }
  ]
}

# --- 10. Stage Scheduler Module (Cost Savings: Off-Hours Shutdown) ---
module "stage_scheduler" {
  count  = var.enable_stage_scheduler ? 1 : 0
  source = "../../modules/stage_scheduler"

  project_name = var.project_name
  environment  = "stage"
  aws_region   = var.aws_region

  ecs_cluster_name = module.ecs.cluster_name
  ecs_service_names = compact([
    module.ecs.api_service_name,
    module.ecs.worker_service_name,
    var.enable_frontend ? module.ecs.frontend_service_name : ""
  ])

  rds_instance_ids = [
    module.rds.db_instance_id
  ]

  stop_cron_utc   = var.scheduler_stop_cron_utc
  start_cron_utc  = var.scheduler_start_cron_utc
  enable_schedule = true
}
