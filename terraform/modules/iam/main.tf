# IAM Roles Module for EstateOS / HRrealestate

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# --- ECS Task Execution Role ---
resource "aws_iam_role" "execution" {
  name        = "${var.project_name}-${var.environment}-ecs-execution-role"
  description = "Allows ECS tasks to call AWS services on your behalf (${var.project_name} ${var.environment})"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-ecs-execution-role"
      Environment = var.environment
    }
  )
}

resource "aws_iam_role_policy_attachment" "execution_standard" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "SecretsManagerRead"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsManagerAccess"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.project_name}/${var.environment}/*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:rds!*"
        ]
      }
    ]
  })
}

# --- ECS Task Role ---
resource "aws_iam_role" "task" {
  name        = "${var.project_name}-${var.environment}-ecs-task-role"
  description = "Allows ECS container tasks to interact with AWS APIs (${var.project_name} ${var.environment})"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-ecs-task-role"
      Environment = var.environment
    }
  )
}

resource "aws_iam_role_policy_attachment" "task_secrets" {
  role       = aws_iam_role.task.name
  policy_arn = "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
}

resource "aws_iam_role_policy" "task_s3" {
  name = "S3ProjectStorageAccess"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.s3_bucket_arn,
          "${var.s3_bucket_arn}/*"
        ]
      }
    ]
  })
}

# --- GitHub Actions OIDC Deploy Role (Optional) ---
locals {
  github_oidc_arn = var.github_oidc_provider_arn != "" ? var.github_oidc_provider_arn : "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions" {
  count       = var.enable_github_actions_role ? 1 : 0
  name        = "${var.project_name}-${var.environment}-github-actions-role"
  description = "Allows GitHub Actions to deploy the ${var.environment} branch to ECS (${var.project_name})"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = local.github_oidc_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_repository}:ref:refs/heads/${var.environment == "prod" ? "main" : "stage"}",
              "repo:${var.github_repository}:ref:refs/heads/${var.environment}"
            ]
          }
        }
      }
    ]
  })

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-github-actions-role"
      Environment = var.environment
    }
  )
}

resource "aws_iam_role_policy_attachment" "gha_ecr" {
  count      = var.enable_github_actions_role ? 1 : 0
  role       = aws_iam_role.github_actions[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
}

resource "aws_iam_role_policy_attachment" "gha_ecs" {
  count      = var.enable_github_actions_role ? 1 : 0
  role       = aws_iam_role.github_actions[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonECS_FullAccess"
}

resource "aws_iam_role_policy" "gha_logs" {
  count = var.enable_github_actions_role ? 1 : 0
  name  = "MigratorCloudWatchLogsPolicy"
  role  = aws_iam_role.github_actions[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowMigratorLogReading"
        Effect = "Allow"
        Action = [
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:DescribeLogStreams",
          "logs:DescribeLogGroups",
          "logs:CreateLogGroup"
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/ecs/${var.project_name}-${var.environment}-*",
          "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/ecs/${var.project_name}-${var.environment}-*:*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "gha_pass_role" {
  count = var.enable_github_actions_role ? 1 : 0
  name  = "PassECSTaskRoles"
  role  = aws_iam_role.github_actions[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "PassTaskRoles"
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = [
          aws_iam_role.execution.arn,
          aws_iam_role.task.arn
        ]
      }
    ]
  })
}

