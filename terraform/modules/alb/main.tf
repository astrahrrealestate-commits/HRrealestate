# Application Load Balancer Module for EstateOS / HRrealestate

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

resource "aws_lb" "this" {
  name               = "${var.project_name}-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_security_group_id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = var.enable_deletion_protection

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-alb"
      Environment = var.environment
    }
  )
}

# --- API Target Group ---
resource "aws_lb_target_group" "api" {
  name        = "${var.project_name}-${var.environment}-api-tg"
  port        = var.app_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = var.health_check_path
    protocol            = "HTTP"
    port                = "traffic-port"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-api-tg"
      Environment = var.environment
    }
  )
}

# --- Optional Frontend Target Group ---
resource "aws_lb_target_group" "frontend" {
  count       = var.enable_frontend ? 1 : 0
  name        = "${var.project_name}-${var.environment}-fe-tg"
  port        = var.frontend_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/"
    protocol            = "HTTP"
    port                = "traffic-port"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200,307,308"
  }

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-fe-tg"
      Environment = var.environment
    }
  )
}

# --- HTTP Listener (Port 80) ---
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = var.certificate_arn != null && var.certificate_arn != "" ? [1] : []
    content {
      type = "redirect"

      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = var.certificate_arn == null || var.certificate_arn == "" ? [1] : []
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.api.arn
    }
  }
}

# --- HTTPS Listener (Port 443) ---
resource "aws_lb_listener" "https" {
  count             = var.certificate_arn != null && var.certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# --- Host-Header Routing Rule for Frontend (HTTPS) ---
resource "aws_lb_listener_rule" "frontend_https" {
  count        = (var.enable_frontend && var.certificate_arn != null && var.certificate_arn != "" && var.frontend_host_header != "") ? 1 : 0
  listener_arn = aws_lb_listener.https[0].arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend[0].arn
  }

  condition {
    host_header {
      values = [for h in split(",", var.frontend_host_header) : trimspace(h)]
    }
  }
}

# --- Host-Header Routing Rule for Frontend (HTTP fallback when no cert) ---
resource "aws_lb_listener_rule" "frontend_http" {
  count        = (var.enable_frontend && (var.certificate_arn == null || var.certificate_arn == "") && var.frontend_host_header != "") ? 1 : 0
  listener_arn = aws_lb_listener.http.arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend[0].arn
  }

  condition {
    host_header {
      values = [for h in split(",", var.frontend_host_header) : trimspace(h)]
    }
  }
}

