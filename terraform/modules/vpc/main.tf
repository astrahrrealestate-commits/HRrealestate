# VPC Module for EstateOS / HRrealestate

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-vpc"
      Environment = var.environment
    }
  )
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-igw"
      Environment = var.environment
    }
  )
}

# --- Public Subnets (for ALB and Public-facing tasks) ---
resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_a_cidr
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-public-a"
      Type        = "Public"
      Environment = var.environment
    }
  )
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_b_cidr
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = true

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-public-b"
      Type        = "Public"
      Environment = var.environment
    }
  )
}

# --- Private Database Subnets ---
resource "aws_subnet" "private_db_a" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.private_db_subnet_a_cidr
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = false

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-private-db-a"
      Type        = "Private-DB"
      Environment = var.environment
    }
  )
}

resource "aws_subnet" "private_db_b" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.private_db_subnet_b_cidr
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = false

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-private-db-b"
      Type        = "Private-DB"
      Environment = var.environment
    }
  )
}

# --- Route Tables & Associations ---
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-public-rt"
      Environment = var.environment
    }
  )
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-private-rt"
      Environment = var.environment
    }
  )
}

resource "aws_route_table_association" "private_db_a" {
  subnet_id      = aws_subnet.private_db_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_db_b" {
  subnet_id      = aws_subnet.private_db_b.id
  route_table_id = aws_route_table.private.id
}

# --- S3 Gateway Endpoint (Zero Cost in-VPC S3 Access) ---
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id, aws_route_table.public.id]

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-s3-gateway-endpoint"
      Environment = var.environment
    }
  )
}

