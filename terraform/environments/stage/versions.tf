terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Backend configuration for remote S3 state storage:
  # backend "s3" {
  #   bucket         = "estateos-terraform-state-830044626379"
  #   key            = "stage/terraform.tfstate"
  #   region         = "eu-central-1"
  #   dynamodb_table = "estateos-terraform-locks"
  # }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = "stage"
      ManagedBy   = "Terraform"
    }
  }
}

