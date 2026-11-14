# Production Environment Terraform Configuration for EstateOS / HRrealestate

locals {
  backend_image  = var.backend_container_image != "" ? var.backend_container_image : "${module.ecr.repository_urls["${var.project_name}/backend"]}:latest"
  frontend_image = var.frontend_container_image != "" ? var.frontend_container_image : (var.enable_frontend ? try("${module.ecr.repository_urls["${var.project_name}/frontend"]}:latest", "") : "")
}

# --- 1. Dedicated Production VPC Module ---
module "vpc" {
  source = "../../modules/vpc"

  aws_region   = var.aws_region
  project_name = var.project_name
  environment  = "prod"
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
  environment   = "prod"
  vpc_id        = module.vpc.vpc_id
  app_port      = var.app_port
  frontend_port = var.frontend_port
}

# --- 3. S3 Project Storage Module ---
module "s3" {
  source = "../../modules/s3"

  project_name      = var.project_name
  environment       = "prod"
  aws_account_id    = var.aws_account_id
  enable_versioning = true
  force_destroy     = false
}

# --- 4. RDS PostgreSQL 16 Module ---
module "rds" {
  source = "../../modules/rds"

  project_name          = var.project_name
  environment           = "prod"
  database_subnet_ids   = module.vpc.private_db_subnet_ids
  rds_security_group_id = module.security_groups.rds_security_group_id

  engine_version               = var.db_engine_version
  instance_class               = var.db_instance_class
  allocated_storage            = var.db_allocated_storage
  max_allocated_storage        = var.db_max_allocated_storage
  db_name                      = var.db_name
  db_username                  = var.db_username
  deletion_protection          = true
  skip_final_snapshot          = false
  multi_az                     = var.multi_az
  performance_insights_enabled = true
  backup_retention_period      = var.backup_retention_period
}

# --- 5. Application Secrets Manager Module ---
module "secrets" {
  source = "../../modules/secrets"

  project_name            = var.project_name
  environment             = "prod"
  recovery_window_in_days = 30
}

# --- 6. ECR Repositories Module ---
module "ecr" {
  source = "../../modules/ecr"

  repository_names = var.enable_frontend ? [
    "${var.project_name}/backend",
    "${var.project_name}/frontend"
  ] : [
    "${var.project_name}/backend"
  ]
}

# --- 7. IAM Roles Module ---
module "iam" {
  source = "../../modules/iam"

  aws_region                 = var.aws_region
  aws_account_id             = var.aws_account_id
  project_name               = var.project_name
  environment                = "prod"
  github_repository          = var.github_repository
  s3_bucket_arn              = module.s3.bucket_arn
  enable_github_actions_role = var.enable_github_actions_role
}

# --- 8. Application Load Balancer Module ---
module "alb" {
  source = "../../modules/alb"

  project_name               = var.project_name
  environment                = "prod"
  vpc_id                     = module.vpc.vpc_id
  public_subnet_ids          = module.vpc.public_subnet_ids
  alb_security_group_id      = module.security_groups.alb_security_group_id
  app_port                   = var.app_port
  health_check_path          = "/health/ready"
  certificate_arn            = var.certificate_arn
  enable_deletion_protection = true

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
  environment               = "prod"
  subnet_ids                = module.vpc.public_subnet_ids
  ecs_security_group_id     = module.security_groups.ecs_security_group_id
  execution_role_arn        = module.iam.execution_role_arn
  task_role_arn             = module.iam.task_role_arn
  api_target_group_arn      = module.alb.api_target_group_arn
  frontend_target_group_arn = module.alb.frontend_target_group_arn
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
  log_retention_days        = 90
  enable_container_insights = true

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
    { name = "LLM_TIMEOUT_SEC", value = "30" },
    { name = "WHATSAPP_PROVIDER", value = "cloud_api" },
    { name = "WHATSAPP_FROM_NUMBER", value = "916364840587" },
    { name = "OWNER_PHONE_NUMBER", value = "916364840587" },
    { name = "OWNER_TEMPLATE_NAME", value = "estateos_pending" },
    { name = "OWNER_TEMPLATE_LANGUAGE", value = "en" },
    { name = "GMAIL_PROVIDER", value = "google" },
    { name = "CALENDAR_PROVIDER", value = "google" },
    { name = "DRIVE_PROVIDER", value = "google" },
    { name = "TENANT_SENDS_PER_HOUR", value = "30" }
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
    { name = "WHATSAPP_VERIFY_TOKEN", valueFrom = "${module.secrets.secret_arn}:WHATSAPP_VERIFY_TOKEN::" }
  ]
}
