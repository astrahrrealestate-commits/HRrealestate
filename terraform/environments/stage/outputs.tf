output "vpc_id" {
  description = "Stage VPC ID"
  value       = module.vpc.vpc_id
}

output "public_subnets" {
  description = "Stage Public Subnet IDs"
  value       = module.vpc.public_subnet_ids
}

output "private_db_subnets" {
  description = "Stage Private Database Subnet IDs"
  value       = module.vpc.private_db_subnet_ids
}

output "alb_dns_name" {
  description = "Public DNS name for Stage Application Load Balancer"
  value       = module.alb.alb_dns_name
}

output "alb_arn" {
  description = "ARN of Stage ALB"
  value       = module.alb.alb_arn
}

output "api_target_group_arn" {
  description = "ARN of Stage API Target Group"
  value       = module.alb.api_target_group_arn
}

output "frontend_target_group_arn" {
  description = "ARN of Stage Frontend Target Group"
  value       = module.alb.frontend_target_group_arn
}

output "db_endpoint" {
  description = "Stage RDS PostgreSQL Endpoint"
  value       = module.rds.db_endpoint
}

output "db_instance_id" {
  description = "Stage RDS DB Instance ID"
  value       = module.rds.db_instance_id
}

output "ecs_cluster_name" {
  description = "Stage ECS Cluster Name"
  value       = module.ecs.cluster_name
}

output "api_ecs_service_name" {
  description = "Stage API ECS Service Name"
  value       = module.ecs.api_service_name
}

output "worker_ecs_service_name" {
  description = "Stage DBOS Worker ECS Service Name"
  value       = module.ecs.worker_service_name
}

output "frontend_ecs_service_name" {
  description = "Stage Frontend ECS Service Name"
  value       = module.ecs.frontend_service_name
}

output "github_actions_deploy_role_arn" {
  description = "IAM Role ARN for Stage GitHub Actions deployment"
  value       = module.iam.github_actions_role_arn
}

output "s3_bucket_id" {
  description = "Stage S3 Storage Bucket"
  value       = module.s3.bucket_id
}

output "secrets_manager_secret_arn" {
  description = "Stage Secrets Manager Secret ARN"
  value       = module.secrets.secret_arn
}

output "ecr_repository_urls" {
  description = "ECR Repository URLs"
  value = {
    "${var.project_name}/backend" = data.aws_ecr_repository.backend.repository_url
  }
}

output "stage_scheduler_lambda_name" {
  description = "Stage Scheduler Lambda Function Name (if enabled)"
  value       = var.enable_stage_scheduler ? module.stage_scheduler[0].lambda_function_name : null
}

