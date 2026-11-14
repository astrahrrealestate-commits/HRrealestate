variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g., stage, prod)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where security groups will be created"
  type        = string
}

variable "app_port" {
  description = "Application port exposed by the backend API container"
  type        = number
  default     = 8000
}

variable "frontend_port" {
  description = "Application port exposed by the frontend container"
  type        = number
  default     = 3000
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

