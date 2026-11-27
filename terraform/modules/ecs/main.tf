# ECS Fargate Cluster & Service Module for EstateOS / HRrealestate

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# --- ECS Cluster ---
resource "aws_ecs_cluster" "this" {
  name = "${var.project_name}-${var.environment}-cluster"

  setting {
    name  = "containerInsights"
    value = var.enable_container_insights ? "enabled" : "disabled"
  }

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-cluster"
      Environment = var.environment
    }
  )
}

# --- CloudWatch Log Groups ---
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project_name}-${var.environment}-api"
  retention_in_days = var.log_retention_days

  tags = merge(
    var.tags,
    {
      Name        = "/ecs/${var.project_name}-${var.environment}-api"
      Environment = var.environment
    }
  )
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project_name}-${var.environment}-worker"
  retention_in_days = var.log_retention_days

  tags = merge(
    var.tags,
    {
      Name        = "/ecs/${var.project_name}-${var.environment}-worker"
      Environment = var.environment
    }
  )
}

resource "aws_cloudwatch_log_group" "migrator" {
  name              = "/ecs/${var.project_name}-${var.environment}-migrator"
  retention_in_days = var.log_retention_days

  tags = merge(
    var.tags,
    {
      Name        = "/ecs/${var.project_name}-${var.environment}-migrator"
      Environment = var.environment
    }
  )
}

resource "aws_cloudwatch_log_group" "frontend" {
  count             = var.enable_frontend ? 1 : 0
  name              = "/ecs/${var.project_name}-${var.environment}-frontend"
  retention_in_days = var.log_retention_days

  tags = merge(
    var.tags,
    {
      Name        = "/ecs/${var.project_name}-${var.environment}-frontend"
      Environment = var.environment
    }
  )
}

# --- 1. Backend API Task Definition ---
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-${var.environment}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.api_cpu)
  memory                   = tostring(var.api_memory)
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.backend_container_image
      essential = true
      command   = ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", tostring(var.app_port)]
      portMappings = [
        {
          containerPort = var.app_port
          hostPort      = var.app_port
          protocol      = "tcp"
        }
      ]
      environment = var.backend_environment_variables
      secrets     = var.backend_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
          "awslogs-create-group"  = "true"
        }
      }
    }
  ])

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-api-task-def"
      Environment = var.environment
    }
  )
}

# --- 2. DBOS Worker Task Definition ---
resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-${var.environment}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory)
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name        = "worker"
      image       = var.backend_container_image
      essential   = true
      command     = ["python", "-m", "app.worker"]
      # DBOS.destroy waits up to 20 s for running steps; the 30 s default SIGKILLs a slow BRIXX step mid-deploy.
      stopTimeout = 60
      environment = var.backend_environment_variables
      secrets     = var.backend_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
          "awslogs-create-group"  = "true"
        }
      }
    }
  ])

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-worker-task-def"
      Environment = var.environment
    }
  )
}

# --- 3. Migrator Task Definition (One-shot DB migration) ---
resource "aws_ecs_task_definition" "migrator" {
  family                   = "${var.project_name}-${var.environment}-migrator"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.api_cpu)
  memory                   = tostring(var.api_memory)
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name        = "migrator"
      image       = var.backend_container_image
      essential   = true
      command     = ["alembic", "upgrade", "head"]
      environment = var.backend_environment_variables
      secrets     = var.backend_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.migrator.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
          "awslogs-create-group"  = "true"
        }
      }
    }
  ])

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-migrator-task-def"
      Environment = var.environment
    }
  )
}

# --- 4. Optional Frontend Task Definition ---
resource "aws_ecs_task_definition" "frontend" {
  count                    = var.enable_frontend ? 1 : 0
  family                   = "${var.project_name}-${var.environment}-frontend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.frontend_cpu)
  memory                   = tostring(var.frontend_memory)
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = var.frontend_container_image
      essential = true
      portMappings = [
        {
          containerPort = var.frontend_port
          hostPort      = var.frontend_port
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "NODE_ENV", value = "production" },
        { name = "PORT", value = tostring(var.frontend_port) }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.frontend[0].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
          "awslogs-create-group"  = "true"
        }
      }
    }
  ])

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-frontend-task-def"
      Environment = var.environment
    }
  )
}

# --- ECS Services ---

# 1. API Service (attached to ALB)
resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-${var.environment}-api-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 0
  }

  enable_execute_command = true

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = var.assign_public_ip
  }

  load_balancer {
    target_group_arn = var.api_target_group_arn
    container_name   = "api"
    container_port   = var.app_port
  }

  health_check_grace_period_seconds = 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_controller {
    type = "ECS"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-api-service"
      Environment = var.environment
    }
  )
}

# 2. DBOS Worker Service (headless async execution)
resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-${var.environment}-worker-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 0
  }

  enable_execute_command = true

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = var.assign_public_ip
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_controller {
    type = "ECS"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-worker-service"
      Environment = var.environment
    }
  )
}

# 3. Frontend Service (attached to ALB if enabled)
resource "aws_ecs_service" "frontend" {
  count           = var.enable_frontend ? 1 : 0
  name            = "${var.project_name}-${var.environment}-fe-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.frontend[0].arn
  desired_count   = var.frontend_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 0
  }

  enable_execute_command = true

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = var.assign_public_ip
  }

  dynamic "load_balancer" {
    for_each = var.frontend_target_group_arn != null ? [1] : []
    content {
      target_group_arn = var.frontend_target_group_arn
      container_name   = "frontend"
      container_port   = var.frontend_port
    }
  }

  deployment_controller {
    type = "ECS"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-fe-service"
      Environment = var.environment
    }
  )
}
