output "cluster_id" {
  description = "ECS Cluster ID"
  value       = aws_ecs_cluster.this.id
}

output "cluster_arn" {
  description = "ECS Cluster ARN"
  value       = aws_ecs_cluster.this.arn
}

output "cluster_name" {
  description = "ECS Cluster Name"
  value       = aws_ecs_cluster.this.name
}

output "api_service_id" {
  description = "ECS API Service ID"
  value       = aws_ecs_service.api.id
}

output "api_service_name" {
  description = "ECS API Service Name"
  value       = aws_ecs_service.api.name
}

output "worker_service_id" {
  description = "ECS DBOS Worker Service ID"
  value       = aws_ecs_service.worker.id
}

output "worker_service_name" {
  description = "ECS DBOS Worker Service Name"
  value       = aws_ecs_service.worker.name
}

output "frontend_service_id" {
  description = "ECS Frontend Service ID"
  value       = var.enable_frontend ? aws_ecs_service.frontend[0].id : null
}

output "frontend_service_name" {
  description = "ECS Frontend Service Name"
  value       = var.enable_frontend ? aws_ecs_service.frontend[0].name : null
}

output "api_task_definition_arn" {
  description = "ECS Task Definition ARN for API"
  value       = aws_ecs_task_definition.api.arn
}

output "worker_task_definition_arn" {
  description = "ECS Task Definition ARN for DBOS Worker"
  value       = aws_ecs_task_definition.worker.arn
}

output "migrator_task_definition_arn" {
  description = "ECS Task Definition ARN for Migrator"
  value       = aws_ecs_task_definition.migrator.arn
}

output "frontend_task_definition_arn" {
  description = "ECS Task Definition ARN for Frontend"
  value       = var.enable_frontend ? aws_ecs_task_definition.frontend[0].arn : null
}

output "api_log_group_name" {
  description = "CloudWatch Log Group Name for API"
  value       = aws_cloudwatch_log_group.api.name
}

output "worker_log_group_name" {
  description = "CloudWatch Log Group Name for Worker"
  value       = aws_cloudwatch_log_group.worker.name
}

output "migrator_log_group_name" {
  description = "CloudWatch Log Group Name for Migrator"
  value       = aws_cloudwatch_log_group.migrator.name
}

output "frontend_log_group_name" {
  description = "CloudWatch Log Group Name for Frontend"
  value       = var.enable_frontend ? aws_cloudwatch_log_group.frontend[0].name : null
}

