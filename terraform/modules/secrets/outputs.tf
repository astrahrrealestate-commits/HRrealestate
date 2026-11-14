output "secret_id" {
  description = "Secrets Manager Secret ID"
  value       = aws_secretsmanager_secret.backend.id
}

output "secret_arn" {
  description = "Secrets Manager Secret ARN"
  value       = aws_secretsmanager_secret.backend.arn
}

output "secret_name" {
  description = "Secrets Manager Secret Name"
  value       = aws_secretsmanager_secret.backend.name
}

