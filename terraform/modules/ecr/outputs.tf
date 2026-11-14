output "repository_arns" {
  description = "Map of ECR repository names to ARNs"
  value       = { for k, v in aws_ecr_repository.this : k => v.arn }
}

output "repository_urls" {
  description = "Map of ECR repository names to repository URLs"
  value       = { for k, v in aws_ecr_repository.this : k => v.repository_url }
}

