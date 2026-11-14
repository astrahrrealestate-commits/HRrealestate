variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Environment (e.g. stage)"
  type        = string
  default     = "stage"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-central-1"
}

variable "ecs_cluster_name" {
  description = "Name of the ECS Cluster to scale"
  type        = string
}

variable "ecs_service_names" {
  description = "List of ECS service names to scale"
  type        = list(string)
}

variable "rds_instance_ids" {
  description = "List of RDS DB instance identifiers to start/stop"
  type        = list(string)
}

variable "stop_cron_utc" {
  description = "Cron expression (UTC) to stop staging servers (default: 15:30 UTC = 9:00 PM IST)"
  type        = string
  default     = "cron(30 15 * * ? *)"
}

variable "start_cron_utc" {
  description = "Cron expression (UTC) to start staging servers (default: 03:30 UTC = 9:00 AM IST)"
  type        = string
  default     = "cron(30 3 * * ? *)"
}

variable "enable_schedule" {
  description = "Whether to enable EventBridge schedule rules"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

