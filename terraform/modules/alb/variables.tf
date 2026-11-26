variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g. stage, prod)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where the ALB and Target Groups will be created"
  type        = string
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs for the ALB"
  type        = list(string)
}

variable "alb_security_group_id" {
  description = "Security Group ID for the ALB"
  type        = string
}

variable "app_port" {
  description = "Backend API port"
  type        = number
  default     = 8000
}

variable "health_check_path" {
  description = "Health check path for backend API"
  type        = string
  default     = "/health/ready"
}

variable "certificate_arn" {
  description = "ACM Certificate ARN for HTTPS listener (optional)"
  type        = string
  default     = null
}

variable "enable_deletion_protection" {
  description = "Enable deletion protection on ALB"
  type        = bool
  default     = false
}

variable "enable_frontend" {
  description = "Whether to provision target group and routing for frontend"
  type        = bool
  default     = false
}

variable "frontend_port" {
  description = "Frontend port"
  type        = number
  default     = 3000
}

variable "frontend_host_header" {
  description = "Host header for routing to frontend (e.g., estateos.hrrealestate.nl)"
  type        = string
  default     = "estateos.hrrealestate.nl"
}

variable "api_host_header" {
  description = "Host header for routing to backend API (e.g., api.estateos.hrrealestate.nl)"
  type        = string
  default     = "api.estateos.hrrealestate.nl"
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

variable "idle_timeout" {
  description = "Seconds a connection may sit idle. Astra's researched answers take up to SUPER_AGENT_DEADLINE_SEC plus the planner, so this stays above both (M13 T15)."
  type        = number
  default     = 60
}
