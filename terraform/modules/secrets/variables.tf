variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (stage or prod)"
  type        = string
}

variable "recovery_window_in_days" {
  description = "Number of days that Secrets Manager waits before deleting the secret (0 for force delete during test/destroy)"
  type        = number
  default     = 0
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

