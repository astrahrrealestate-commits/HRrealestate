output "vpc_id" {
  description = "Production VPC ID"
  value       = module.vpc.vpc_id
}

output "public_subnets" {
  description = "Production Public Subnet IDs"
  value       = module.vpc.public_subnet_ids
}

output "private_db_subnets" {
  description = "Production Private Database Subnet IDs"
  value       = module.vpc.private_db_subnet_ids
}

output "alb_dns_name" {
  description = "Public DNS name for Production Application Load Balancer"
  value       = module.alb.alb_dns_name
}

output "alb_arn" {
  description = "ARN of Production ALB"
  value       = module.alb.alb_arn
}

output "api_target_group_arn" {
  description = "ARN of Production API Target Group"
  value       = module.alb.api_target_group_arn
}

output "frontend_target_group_arn" {
  description = "ARN of Production Frontend Target Group"
  value       = module.alb.frontend_target_group_arn
}

output "db_endpoint" {
  description = "Production RDS PostgreSQL Endpoint"
  value       = module.rds.db_endpoint
}

output "db_instance_id" {
  description = "Production RDS DB Instance ID"
  value       = module.rds.db_instance_id
}

output "ecs_cluster_name" {
  description = "Production ECS Cluster Name"
  value       = module.ecs.cluster_name
}

output "api_ecs_service_name" {
  description = "Production API ECS Service Name"
  value       = module.ecs.api_service_name
}

output "worker_ecs_service_name" {
  description = "Production DBOS Worker ECS Service Name"
  value       = module.ecs.worker_service_name
}

output "frontend_ecs_service_name" {
  description = "Production Frontend ECS Service Name"
  value       = module.ecs.frontend_service_name
}

output "github_actions_deploy_role_arn" {
  description = "IAM Role ARN for Production GitHub Actions deployment"
  value       = module.iam.github_actions_role_arn
}

output "s3_bucket_id" {
  description = "Production S3 Storage Bucket"
  value       = module.s3.bucket_id
}

output "secrets_manager_secret_arn" {
  description = "Production Secrets Manager Secret ARN"
  value       = module.secrets.secret_arn
}

output "ecr_repository_urls" {
  description = "ECR Repository URLs"
  value       = module.ecr.repository_urls
}

