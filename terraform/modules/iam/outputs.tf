output "execution_role_arn" {
  description = "ECS Task Execution Role ARN"
  value       = aws_iam_role.execution.arn
}

output "execution_role_name" {
  description = "ECS Task Execution Role Name"
  value       = aws_iam_role.execution.name
}

output "task_role_arn" {
  description = "ECS Task Role ARN"
  value       = aws_iam_role.task.arn
}

output "task_role_name" {
  description = "ECS Task Role Name"
  value       = aws_iam_role.task.name
}

output "github_actions_role_arn" {
  description = "GitHub Actions OIDC Deploy Role ARN (if enabled)"
  value       = var.enable_github_actions_role ? aws_iam_role.github_actions[0].arn : null
}

output "github_actions_role_name" {
  description = "GitHub Actions OIDC Deploy Role Name (if enabled)"
  value       = var.enable_github_actions_role ? aws_iam_role.github_actions[0].name : null
}

