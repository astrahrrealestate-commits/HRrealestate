output "lambda_function_arn" {
  description = "ARN of the stage scheduler Lambda function"
  value       = aws_lambda_function.scheduler.arn
}

output "lambda_function_name" {
  description = "Name of the stage scheduler Lambda function"
  value       = aws_lambda_function.scheduler.function_name
}

output "stop_rule_arn" {
  description = "ARN of the EventBridge nightly stop rule"
  value       = aws_cloudwatch_event_rule.stop_rule.arn
}

output "start_rule_arn" {
  description = "ARN of the EventBridge morning start rule"
  value       = aws_cloudwatch_event_rule.start_rule.arn
}

