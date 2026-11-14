variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g., stage, prod)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "public_subnet_a_cidr" {
  description = "CIDR block for public subnet in AZ a"
  type        = string
}

variable "public_subnet_b_cidr" {
  description = "CIDR block for public subnet in AZ b"
  type        = string
}

variable "private_db_subnet_a_cidr" {
  description = "CIDR block for private DB subnet in AZ a"
  type        = string
}

variable "private_db_subnet_b_cidr" {
  description = "CIDR block for private DB subnet in AZ b"
  type        = string
}

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}

