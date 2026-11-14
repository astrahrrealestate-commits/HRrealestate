variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (stage or prod)"
  type        = string
}

variable "database_subnet_ids" {
  description = "Subnet IDs for the database subnet group"
  type        = list(string)
}

variable "rds_security_group_id" {
  description = "Security Group ID for RDS"
  type        = string
}

variable "engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "16.4"
}

variable "instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "Maximum storage auto-scaling in GB"
  type        = number
  default     = 100
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "estateos"
}

variable "db_username" {
  description = "Master database username"
  type        = string
  default     = "estateos"
}

variable "multi_az" {
  description = "Enable Multi-AZ deployment"
  type        = bool
  default     = false
}

variable "backup_retention_period" {
  description = "Days to retain automated backups"
  type        = number
  default     = 7
}

variable "backup_window" {
  description = "Daily backup window (UTC)"
  type        = string
  default     = "03:00-04:00"
}

variable "maintenance_window" {
  description = "Weekly maintenance window (UTC)"
  type        = string
  default     = "Mon:04:00-Mon:05:00"
}

variable "deletion_protection" {
  description = "Protect DB against accidental deletion"
  type        = bool
  default     = false
}

variable "performance_insights_enabled" {
  description = "Enable RDS Performance Insights"
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Skip final snapshot before DB deletion"
  type        = bool
  default     = true
}

variable "kms_key_arn" {
  description = "ARN of KMS key for storage encryption"
  type        = string
  default     = null
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

