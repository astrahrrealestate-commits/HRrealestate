output "alb_security_group_id" {
  description = "Security group ID for Application Load Balancer"
  value       = aws_security_group.alb.id
}

output "ecs_security_group_id" {
  description = "Security group ID for ECS Tasks"
  value       = aws_security_group.ecs.id
}

output "rds_security_group_id" {
  description = "Security group ID for RDS PostgreSQL"
  value       = aws_security_group.rds.id
}

output "vpc_endpoints_security_group_id" {
  description = "Security group ID for VPC Endpoints"
  value       = aws_security_group.vpc_endpoints.id
}

