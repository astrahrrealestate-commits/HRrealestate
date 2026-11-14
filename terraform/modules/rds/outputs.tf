output "db_instance_id" {
  description = "RDS DB Instance Identifier"
  value       = aws_db_instance.this.id
}

output "db_instance_arn" {
  description = "RDS DB Instance ARN"
  value       = aws_db_instance.this.arn
}

output "db_endpoint" {
  description = "RDS DB connection endpoint host:port"
  value       = aws_db_instance.this.endpoint
}

output "db_address" {
  description = "RDS DB address host"
  value       = aws_db_instance.this.address
}

output "db_port" {
  description = "RDS DB port"
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "Database name"
  value       = aws_db_instance.this.db_name
}

output "master_user_secret_arn" {
  description = "ARN of the Secrets Manager secret for master DB user"
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

