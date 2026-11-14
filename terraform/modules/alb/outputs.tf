output "alb_id" {
  description = "ALB ID"
  value       = aws_lb.this.id
}

output "alb_arn" {
  description = "ALB ARN"
  value       = aws_lb.this.arn
}

output "alb_dns_name" {
  description = "ALB DNS Name"
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  description = "ALB Canonical Hosted Zone ID"
  value       = aws_lb.this.zone_id
}

output "api_target_group_arn" {
  description = "API Target Group ARN"
  value       = aws_lb_target_group.api.arn
}

output "api_target_group_name" {
  description = "API Target Group Name"
  value       = aws_lb_target_group.api.name
}

output "frontend_target_group_arn" {
  description = "Frontend Target Group ARN (if created)"
  value       = var.enable_frontend ? aws_lb_target_group.frontend[0].arn : null
}

output "http_listener_arn" {
  description = "HTTP Listener ARN"
  value       = aws_lb_listener.http.arn
}

output "https_listener_arn" {
  description = "HTTPS Listener ARN"
  value       = length(aws_lb_listener.https) > 0 ? aws_lb_listener.https[0].arn : null
}

