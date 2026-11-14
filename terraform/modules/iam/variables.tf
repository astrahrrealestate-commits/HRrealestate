variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "eu-central-1"
}

variable "aws_account_id" {
  description = "AWS Account ID"
  type        = string
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (stage or prod)"
  type        = string
}

variable "github_repository" {
  description = "GitHub repository in format owner/repo (e.g. astrahrrealestate-commits/HRrealestate)"
  type        = string
  default     = "astrahrrealestate-commits/HRrealestate"
}

variable "s3_bucket_arn" {
  description = "ARN of the project's S3 bucket"
  type        = string
}

variable "enable_github_actions_role" {
  description = "Whether to create the GitHub Actions OIDC deploy role"
  type        = bool
  default     = false
}

variable "github_oidc_provider_arn" {
  description = "ARN of GitHub OIDC provider (if empty, constructs default ARN)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

