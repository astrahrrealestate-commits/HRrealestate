variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g., stage, prod)"
  type        = string
}

variable "aws_account_id" {
  description = "AWS Account ID used to create a globally unique bucket name"
  type        = string
}

variable "enable_versioning" {
  description = "Enable versioning on the S3 bucket"
  type        = bool
  default     = true
}

variable "force_destroy" {
  description = "Allow bucket deletion even if non-empty"
  type        = bool
  default     = false
}

variable "kms_master_key_id" {
  description = "KMS Master Key ID/ARN for SSE-KMS (null = AES256)"
  type        = string
  default     = null
}

variable "cors_rules" {
  description = "List of CORS rules for S3 bucket"
  type = list(object({
    allowed_headers = list(string)
    allowed_methods = list(string)
    allowed_origins = list(string)
    expose_headers  = optional(list(string))
    max_age_seconds = optional(number)
  }))
  default = [
    {
      allowed_headers = ["*"]
      allowed_methods = ["GET", "PUT", "POST", "HEAD"]
      allowed_origins = ["*"]
      expose_headers  = ["ETag"]
      max_age_seconds = 3000
    }
  ]
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

