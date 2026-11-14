aws_region        = "eu-north-1"
aws_profile       = "estateos"
aws_account_id    = "830044626379"
project_name      = "estateos"
github_repository = "astrahrrealestate-commits/HRrealestate"

# Dedicated Production VPC Subnets (10.20.0.0/16)
vpc_cidr                 = "10.20.0.0/16"
public_subnet_a_cidr     = "10.20.1.0/24"
public_subnet_b_cidr     = "10.20.2.0/24"
private_db_subnet_a_cidr = "10.20.21.0/24"
private_db_subnet_b_cidr = "10.20.22.0/24"

app_port      = 8000
frontend_port = 3000

# Database (PostgreSQL 16)
db_engine_version        = "16.11"
db_instance_class        = "db.t3.micro"
db_allocated_storage     = 20
db_max_allocated_storage = 100
db_name                  = "estateos"
db_username              = "estateos"
multi_az                 = false
backup_retention_period  = 1

# ALB & Routing
enable_frontend      = false
frontend_host_header = "estateos.hrrealestate.nl, app.estateos.hrrealestate.nl"
api_host_header      = "api-estateos.hrrealestate.nl"
certificate_arn      = "arn:aws:acm:eu-north-1:830044626379:certificate/0da93ff3-b1be-4462-a2bc-f2cd28fa7d05"

# Production Compute (0.5 vCPU = 512 units, 1024 MB RAM)
api_cpu           = 512
api_memory        = 1024
api_desired_count = 1

worker_cpu           = 512
worker_memory        = 1024
worker_desired_count = 1

# Frontend is hosted on Vercel (https://estateos.hrrealestate.nl)
frontend_cpu           = 256
frontend_memory        = 512
frontend_desired_count = 0

# Application URLs
frontend_base_url         = "https://estateos.hrrealestate.nl"
google_login_redirect_uri = "https://api-estateos.hrrealestate.nl/api/auth/login/google/callback"
dashboard_cors_origins    = "https://estateos.hrrealestate.nl"
