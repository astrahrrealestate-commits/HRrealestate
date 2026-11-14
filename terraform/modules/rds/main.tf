# RDS PostgreSQL Module for EstateOS / HRrealestate

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

resource "aws_db_subnet_group" "this" {
  name        = "${var.project_name}-${var.environment}-db-subnet-group"
  description = "DB subnet group for ${var.project_name} ${var.environment} PostgreSQL database"
  subnet_ids  = var.database_subnet_ids

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-db-subnet-group"
      Environment = var.environment
    }
  )
}

resource "aws_db_parameter_group" "this" {
  name        = "${var.project_name}-${var.environment}-pg16"
  family      = "postgres16"
  description = "Custom parameter group for PostgreSQL 16 (${var.project_name} ${var.environment})"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-pg16"
      Environment = var.environment
    }
  )
}

resource "aws_db_instance" "this" {
  identifier                    = "${var.project_name}-${var.environment}-db"
  engine                        = "postgres"
  engine_version                = var.engine_version
  instance_class                = var.instance_class
  allocated_storage             = var.allocated_storage
  max_allocated_storage         = var.max_allocated_storage
  storage_type                  = "gp3"
  iops                          = var.allocated_storage >= 400 ? 3000 : null
  storage_throughput            = var.allocated_storage >= 400 ? 125 : null
  db_name                       = var.db_name
  username                      = var.db_username
  manage_master_user_password   = true
  master_user_secret_kms_key_id = var.kms_key_arn

  storage_encrypted      = true
  kms_key_id             = var.kms_key_arn
  publicly_accessible    = false
  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.rds_security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name

  backup_retention_period    = var.backup_retention_period
  backup_window              = var.backup_window
  maintenance_window         = var.maintenance_window
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  deletion_protection        = var.deletion_protection

  performance_insights_enabled          = var.performance_insights_enabled
  performance_insights_retention_period = var.performance_insights_enabled ? 7 : null
  performance_insights_kms_key_id       = var.performance_insights_enabled ? var.kms_key_arn : null

  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = "${var.project_name}-${var.environment}-db-final-snapshot"

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-db"
      Environment = var.environment
    }
  )
}

