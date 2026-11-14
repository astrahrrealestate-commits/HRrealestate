# Secrets Manager Module for EstateOS / HRrealestate

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

resource "aws_secretsmanager_secret" "backend" {
  name                    = "${var.project_name}/${var.environment}/backend"
  description             = "Application secrets for ${var.project_name} ${var.environment} backend services"
  recovery_window_in_days = var.recovery_window_in_days

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}/${var.environment}/backend"
      Environment = var.environment
    }
  )
}

# Initial placeholder secret version with expected keys; lifecycle ignores subsequent changes
resource "aws_secretsmanager_secret_version" "backend_template" {
  secret_id = aws_secretsmanager_secret.backend.id
  secret_string = jsonencode({
    DATABASE_URL               = ""
    OPENAI_API_KEY             = ""
    GEMINI_API_KEY             = ""
    GROQ_API_KEY               = ""
    SENTRY_DSN                 = ""
    LANGFUSE_PUBLIC_KEY        = ""
    LANGFUSE_SECRET_KEY        = ""
    DASHBOARD_SESSION_SECRET   = ""
    GOOGLE_OAUTH_CLIENT_ID     = ""
    GOOGLE_OAUTH_CLIENT_SECRET = ""
    WHATSAPP_ACCESS_TOKEN      = ""
    WHATSAPP_PHONE_NUMBER_ID   = ""
    WHATSAPP_APP_SECRET        = ""
    WHATSAPP_VERIFY_TOKEN      = ""
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
