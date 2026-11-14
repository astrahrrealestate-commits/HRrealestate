variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "eu-central-1"
}

variable "aws_profile" {
  description = "AWS CLI named profile to use for authentication"
  type        = string
  default     = "estateos"
}

variable "aws_account_id" {
  description = "AWS Account ID"
  type        = string
  default     = "830044626379"
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
  default     = "estateos"
}

variable "github_repository" {
  description = "GitHub repository owner/name"
  type        = string
  default     = "astrahrrealestate-commits/HRrealestate"
}

variable "enable_github_actions_role" {
  description = "Whether to create the GitHub Actions OIDC deploy role"
  type        = bool
  default     = false
}

# --- Networking (Dedicated Prod CIDRs) ---
variable "vpc_cidr" {
  description = "CIDR block for the prod VPC"
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_a_cidr" {
  type    = string
  default = "10.20.1.0/24"
}

variable "public_subnet_b_cidr" {
  type    = string
  default = "10.20.2.0/24"
}

variable "private_db_subnet_a_cidr" {
  type    = string
  default = "10.20.21.0/24"
}

variable "private_db_subnet_b_cidr" {
  type    = string
  default = "10.20.22.0/24"
}

# --- Ports ---
variable "app_port" {
  description = "Backend FastAPI port"
  type        = number
  default     = 8000
}

variable "frontend_port" {
  description = "Frontend Next.js port"
  type        = number
  default     = 3000
}

# --- Database ---
variable "db_engine_version" {
  type    = string
  default = "16.4"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_allocated_storage" {
  type    = number
  default = 50
}

variable "db_max_allocated_storage" {
  type    = number
  default = 200
}

variable "db_name" {
  type    = string
  default = "estateos"
}

variable "db_username" {
  type    = string
  default = "estateos"
}

variable "multi_az" {
  type    = bool
  default = true
}

variable "backup_retention_period" {
  type    = number
  default = 30
}

# --- ALB & Domains ---
variable "certificate_arn" {
  description = "ACM Certificate ARN for HTTPS listener"
  type        = string
  default     = null
}

variable "enable_frontend" {
  description = "Whether to provision the frontend service & target group"
  type        = bool
  default     = true
}

variable "frontend_host_header" {
  description = "Host header for frontend dashboard routing"
  type        = string
  default     = "estateos.hrrealestate.nl, app.estateos.hrrealestate.nl"
}

variable "api_host_header" {
  description = "Host header for backend API routing"
  type        = string
  default     = "api.estateos.hrrealestate.nl"
}

# --- Compute & Containers ---
variable "api_cpu" {
  type    = number
  default = 1024
}

variable "api_memory" {
  type    = number
  default = 2048
}

variable "worker_cpu" {
  type    = number
  default = 1024
}

variable "worker_memory" {
  type    = number
  default = 2048
}

variable "frontend_cpu" {
  type    = number
  default = 512
}

variable "frontend_memory" {
  type    = number
  default = 1024
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "worker_desired_count" {
  type    = number
  default = 2
}

variable "frontend_desired_count" {
  type    = number
  default = 2
}

variable "backend_container_image" {
  description = "ECR image URI for backend containers (API, Worker, Migrator)"
  type        = string
  default     = ""
}

variable "frontend_container_image" {
  description = "ECR image URI for frontend container"
  type        = string
  default     = ""
}

# --- Application Configuration ---
variable "frontend_base_url" {
  description = "Public URL of the frontend dashboard"
  type        = string
  default     = "https://estateos.hrrealestate.nl"
}

variable "google_login_redirect_uri" {
  description = "OAuth redirect URI for Google login"
  type        = string
  default     = "https://api.estateos.hrrealestate.nl/api/auth/login/google/callback"
}

variable "dashboard_cors_origins" {
  description = "Allowed CORS origins for the backend API"
  type        = string
  default     = "https://estateos.hrrealestate.nl"
}

