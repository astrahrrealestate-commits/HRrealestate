variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g., stage, prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-central-1"
}

variable "subnet_ids" {
  description = "Subnet IDs for ECS tasks"
  type        = list(string)
}

variable "ecs_security_group_id" {
  description = "Security Group ID for ECS tasks"
  type        = string
}

variable "execution_role_arn" {
  description = "ECS Task Execution Role ARN"
  type        = string
}

variable "task_role_arn" {
  description = "ECS Task Role ARN"
  type        = string
}

variable "api_target_group_arn" {
  description = "Target Group ARN for backend API"
  type        = string
}

variable "frontend_target_group_arn" {
  description = "Target Group ARN for frontend (optional)"
  type        = string
  default     = null
}

variable "backend_container_image" {
  description = "ECR image URI for backend (API, Worker, Migrator)"
  type        = string
}

variable "frontend_container_image" {
  description = "ECR image URI for frontend dashboard"
  type        = string
  default     = ""
}

variable "app_port" {
  description = "Port exposed by the backend container"
  type        = number
  default     = 8000
}

variable "frontend_port" {
  description = "Port exposed by the frontend container"
  type        = number
  default     = 3000
}

variable "api_cpu" {
  description = "CPU units for API container (256, 512, 1024, etc.)"
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Memory for API container in MiB (512, 1024, 2048, etc.)"
  type        = number
  default     = 1024
}

variable "worker_cpu" {
  description = "CPU units for DBOS worker container"
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Memory for DBOS worker container in MiB"
  type        = number
  default     = 1024
}

variable "frontend_cpu" {
  description = "CPU units for frontend container"
  type        = number
  default     = 256
}

variable "frontend_memory" {
  description = "Memory for frontend container in MiB"
  type        = number
  default     = 512
}

variable "api_desired_count" {
  description = "Desired number of API container instances"
  type        = number
  default     = 1
}

variable "worker_desired_count" {
  description = "Desired number of DBOS worker container instances"
  type        = number
  default     = 1
}

variable "frontend_desired_count" {
  description = "Desired number of frontend container instances"
  type        = number
  default     = 1
}

variable "enable_frontend" {
  description = "Whether to provision the frontend ECS task & service"
  type        = bool
  default     = false
}

variable "assign_public_ip" {
  description = "Assign public IP to ECS tasks in public subnets"
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "enable_container_insights" {
  description = "Enable CloudWatch Container Insights on the cluster"
  type        = bool
  default     = false
}

variable "backend_environment_variables" {
  description = "List of environment variables for backend containers"
  type = list(object({
    name  = string
    value = string
  }))
  default = []
}

variable "backend_secrets" {
  description = "List of Secrets Manager secrets for backend containers"
  type = list(object({
    name      = string
    valueFrom = string
  }))
  default = []
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

