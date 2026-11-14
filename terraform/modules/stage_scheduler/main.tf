# Stage Environment Scheduler Module for EstateOS / HRrealestate

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
  }
}

# --- Package Lambda Function Code ---
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/index.py"
  output_path = "${path.module}/lambda/stage_scheduler.zip"
}

# --- IAM Role for Lambda ---
resource "aws_iam_role" "scheduler_lambda_role" {
  name = "${var.project_name}-${var.environment}-scheduler-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-scheduler-lambda-role"
      Environment = var.environment
    }
  )
}

# --- IAM Policy for Scheduler Lambda ---
resource "aws_iam_policy" "scheduler_lambda_policy" {
  name        = "${var.project_name}-${var.environment}-scheduler-lambda-policy"
  description = "IAM Policy allowing Lambda to start/stop ECS Fargate services and RDS instances"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # CloudWatch Logging
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      # ECS permissions
      {
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices"
        ]
        Resource = "*"
      },
      # RDS permissions
      {
        Effect = "Allow"
        Action = [
          "rds:StartDBInstance",
          "rds:StopDBInstance",
          "rds:DescribeDBInstances"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "scheduler_lambda_attach" {
  role       = aws_iam_role.scheduler_lambda_role.name
  policy_arn = aws_iam_policy.scheduler_lambda_policy.arn
}

# --- CloudWatch Log Group for Lambda ---
resource "aws_cloudwatch_log_group" "scheduler_lambda_logs" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-scheduler"
  retention_in_days = 14

  tags = merge(
    var.tags,
    {
      Name        = "/aws/lambda/${var.project_name}-${var.environment}-scheduler"
      Environment = var.environment
    }
  )
}

# --- Lambda Function ---
resource "aws_lambda_function" "scheduler" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_name}-${var.environment}-scheduler"
  role             = aws_iam_role.scheduler_lambda_role.arn
  handler          = "index.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 60
  memory_size      = 128

  depends_on = [
    aws_iam_role_policy_attachment.scheduler_lambda_attach,
    aws_cloudwatch_log_group.scheduler_lambda_logs
  ]

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-scheduler"
      Environment = var.environment
    }
  )
}

# --- EventBridge Nightly Stop Rule ---
resource "aws_cloudwatch_event_rule" "stop_rule" {
  name                = "${var.project_name}-${var.environment}-nightly-stop"
  description         = "Trigger daily stage shutdown (${var.project_name})"
  schedule_expression = var.stop_cron_utc
  state               = var.enable_schedule ? "ENABLED" : "DISABLED"

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-nightly-stop"
      Environment = var.environment
    }
  )
}

resource "aws_cloudwatch_event_target" "stop_target" {
  rule      = aws_cloudwatch_event_rule.stop_rule.name
  target_id = "StageStopLambdaTarget"
  arn       = aws_lambda_function.scheduler.arn

  input = jsonencode({
    action            = "stop"
    ecs_cluster_name  = var.ecs_cluster_name
    ecs_service_names = var.ecs_service_names
    rds_instance_ids  = var.rds_instance_ids
  })
}

resource "aws_lambda_permission" "allow_cloudwatch_stop" {
  statement_id  = "AllowExecutionFromEventBridgeStop"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.stop_rule.arn
}

# --- EventBridge Morning Start Rule ---
resource "aws_cloudwatch_event_rule" "start_rule" {
  name                = "${var.project_name}-${var.environment}-morning-start"
  description         = "Trigger daily stage startup (${var.project_name})"
  schedule_expression = var.start_cron_utc
  state               = var.enable_schedule ? "ENABLED" : "DISABLED"

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-morning-start"
      Environment = var.environment
    }
  )
}

resource "aws_cloudwatch_event_target" "start_target" {
  rule      = aws_cloudwatch_event_rule.start_rule.name
  target_id = "StageStartLambdaTarget"
  arn       = aws_lambda_function.scheduler.arn

  input = jsonencode({
    action            = "start"
    ecs_cluster_name  = var.ecs_cluster_name
    ecs_service_names = var.ecs_service_names
    rds_instance_ids  = var.rds_instance_ids
  })
}

resource "aws_lambda_permission" "allow_cloudwatch_start" {
  statement_id  = "AllowExecutionFromEventBridgeStart"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.start_rule.arn
}

