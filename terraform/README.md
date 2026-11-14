# EstateOS / HRrealestate — Terraform Infrastructure as Code (IaC)

This directory contains the production-grade Terraform infrastructure for **HRrealestate** (**EstateOS**), supporting fully isolated **Stage** and **Production** environments on AWS with the same proven architecture as Crusource while maintaining dedicated, separate resources.

---

## 1. Architecture Overview

```
                                          +---------------------------------------+
                                          |            Internet Clients           |
                                          +-------------------+-------------------+
                                                              |
                                                              v  Route 53 / DNS
                                          +---------------------------------------+
                                          |   Application Load Balancer (ALB)     |
                                          |   - Port 80 (HTTP -> HTTPS Redirect)  |
                                          |   - Port 443 (TLS 1.3 Termination)    |
                                          +---------+-------------------+---------+
                                                    |                   |
                                   Host Header:     |                   |  Host Header:
                                   api.* / default  |                   |  app.*
                                                    v                   v
                                     +--------------------+      +--------------------+
                                     | Backend Target Grp |      | Frontend Target Grp|
                                     |   (Port 8000)      |      |   (Port 3000)      |
                                     +---------+----------+      +---------+----------+
                                               |                           |
            ===================================|===========================|====================================
            VPC Subnets (Public)               v                           v
                                     +--------------------+      +--------------------+
                                     |  ECS Task: API     |      | ECS Task: Frontend |
                                     |  (FastAPI Backend) |      | (Next.js Dashboard)|
                                     +---------+----------+      +--------------------+
                                               |
                                               v (DBOS async jobs / shared DB)
                                     +--------------------+
                                     |  ECS Task: Worker  |
                                     |  (DBOS Executor)   |
                                     +---------+----------+
            ===================================|================================================================
            VPC Subnets (Private Database)     v Port 5432 (SSL forced)
                                     +------------------------------------------------+
                                     |         Amazon RDS PostgreSQL 16               |
                                     |         - pgvector Extension Enabled           |
                                     |         - Managed Secrets Manager Password     |
                                     |         - GP3 Encrypted Storage                |
                                     +------------------------------------------------+

            Supporting Cloud Services:
            +----------------------+     +----------------------+     +----------------------+
            |    AWS S3 Storage    |     |  AWS Secrets Manager |     |     Amazon ECR       |
            | (Media, Docs, Attach)|     | (API Keys & Secrets) |     |  (Container Images)  |
            +----------------------+     +----------------------+     +----------------------+

            Stage-Only Automation:
            +---------------------------------------------------------------------------------+
            | EventBridge Rules (9:00 PM Stop / 9:00 AM Start IST) -> Lambda Stage Scheduler |
            | Scales ECS to 0 and stops RDS overnight (saves ~50-70% in monthly compute costs)|
            +---------------------------------------------------------------------------------+
```

---

## 2. Directory Structure

```
terraform/
├── environments/
│   ├── stage/                      # Dedicated Staging Environment
│   │   ├── main.tf                 # Stage module orchestration
│   │   ├── variables.tf            # Configurable variables & defaults
│   │   ├── outputs.tf              # Exported endpoints, ARNs, names
│   │   ├── versions.tf             # Terraform & AWS provider requirements
│   │   ├── terraform.tfvars.example# Template for stage variables
│   │   └── terraform.tfvars        # Active stage configuration values
│   │
│   └── prod/                       # Dedicated Production Environment
│       ├── main.tf                 # Production module orchestration
│       ├── variables.tf            # Configurable variables & defaults
│       ├── outputs.tf              # Exported endpoints, ARNs, names
│       ├── versions.tf             # Terraform & AWS provider requirements
│       ├── terraform.tfvars.example# Template for prod variables
│       └── terraform.tfvars        # Active production configuration values
│
└── modules/                        # Reusable Infrastructure Modules
    ├── vpc/                        # Dedicated VPC, subnets, IGW, routes, S3 gateway endpoint
    ├── security_groups/            # Least-privilege SGs for ALB, ECS, RDS, VPC endpoints
    ├── rds/                        # PostgreSQL 16 RDS instance with pgvector & auto-managed password
    ├── alb/                        # Application Load Balancer with HTTP/HTTPS listeners & target groups
    ├── iam/                        # ECS Execution, ECS Task, and GitHub Actions OIDC deploy roles
    ├── ecs/                        # ECS Fargate Cluster, Task Definitions (API, Worker, Migrator, Frontend), Services
    ├── s3/                         # S3 storage bucket with versioning, SSE, and CORS
    ├── secrets/                    # Secrets Manager secret with EstateOS key templates
    ├── ecr/                        # ECR repositories with image scan and lifecycle policies
    └── stage_scheduler/            # Lambda + EventBridge rules for nightly shutdown / morning startup
```

---

## 3. Environment Isolation & Differences

Stage and production maintain completely separate resources in separate subnets and CIDR spaces to avoid any IP collisions or accidental cross-talk:

| Feature / Resource | Stage Environment | Production Environment |
|---|---|---|
| **VPC CIDR** | `10.10.0.0/16` | `10.20.0.0/16` |
| **Public Subnets** | `10.10.1.0/24`, `10.10.2.0/24` | `10.20.1.0/24`, `10.20.2.0/24` |
| **Private DB Subnets** | `10.10.21.0/24`, `10.10.22.0/24` | `10.20.21.0/24`, `10.20.22.0/24` |
| **RDS Instance Class** | `db.t3.micro` | `db.t4g.medium` (or higher) |
| **RDS High Availability** | Single-AZ | Multi-AZ enabled |
| **RDS Storage** | 20 GB gp3 (auto-scale to 100 GB) | 50 GB gp3 (auto-scale to 200 GB) |
| **RDS Deletion Protection**| `false` (fast teardown) | `true` (safe against accidental delete) |
| **RDS Backups** | 7 days retention | 30 days retention + PITR |
| **API Task Sizing** | 512 CPU (0.5 vCPU) / 1024 MiB | 1024 CPU (1.0 vCPU) / 2048 MiB |
| **API Desired Count** | 1 instance | 2 instances (redundant) |
| **Worker Desired Count** | 1 instance | 2 instances |
| **ECS Container Insights** | Disabled | Enabled |
| **CloudWatch Log Retention**| 14 days | 90 days |
| **ALB Deletion Protection** | `false` | `true` |
| **Cost-Saving Scheduler** | **Enabled** (9:00 PM - 9:00 AM IST) | **Disabled** (24/7/365 availability) |
| **GitHub Actions Branch** | Scoped to `stage` branch | Scoped to `main` branch |

---

## 4. Modules Detail

### 1. `vpc`
- Dedicated VPC per environment.
- Two public subnets across 2 Availability Zones (`a` and `b`).
- Two private database subnets across 2 Availability Zones.
- S3 Gateway VPC Endpoint attached to all route tables for free, secure intra-AWS S3 traffic.

### 2. `security_groups`
- **ALB SG**: Ingress on ports 80 and 443 from `0.0.0.0/0` and `::/0`.
- **ECS SG**: Allows inbound traffic from ALB SG on port 8000 (API) and port 3000 (Frontend).
- **RDS SG**: Strictly restricts PostgreSQL port 5432 to ECS SG only.
- **VPC Endpoints SG**: Restricts HTTPS port 443 to ECS SG.

### 3. `rds`
- PostgreSQL 16 with native `pgvector` support (HNSW cosine similarity indexing used by EstateOS memory/RAG).
- Parameter group forces TLS/SSL (`rds.force_ssl = 1`).
- Master user password auto-generated and safely stored in AWS Secrets Manager (`manage_master_user_password = true`).

### 4. `alb`
- Application Load Balancer in public subnets.
- HTTP Listener (port 80) redirects to HTTPS (port 443) when a certificate is provided.
- Target Groups for backend API (`/health/ready` health check) and Next.js frontend (`/` health check).
- Host-header rules for `api.<domain>` and `app.<domain>`.

### 5. `iam`
- **ECS Execution Role**: Standard execution policy + scoped Secrets Manager access for app secrets and RDS secrets.
- **ECS Task Role**: S3 access to project bucket, Secrets Manager read/write, CloudWatch logging.
- **GitHub Actions OIDC Deploy Role**: Passwordless CI/CD authentication via GitHub OIDC provider, scoped strictly to the project's repository and branch.

### 6. `ecs`
- Fargate cluster with Container Insights.
- Task definitions:
  - `api`: FastAPI backend (`uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`).
  - `worker`: DBOS background executor (`python -m app.worker`).
  - `migrator`: One-shot database migrations (`alembic upgrade head`).
  - `frontend`: Next.js web application (port 3000).
- Services configured with `lifecycle { ignore_changes = [task_definition, desired_count] }` to ensure zero drift between CI/CD deployments and the cost-saving scheduler.

### 7. `s3`
- Dedicated S3 bucket `${project_name}-${environment}-storage-${account_id}`.
- S3 versioning enabled for data integrity.
- Public access blocked on all 4 dimensions.
- Configured CORS rules for frontend presigned uploads.

### 8. `secrets`
- AWS Secrets Manager secret `${project_name}/${environment}/backend`.
- Pre-populated with template keys for OpenAI, Gemini, Groq, WhatsApp, Gmail, and Langfuse.
- `lifecycle { ignore_changes = [secret_string] }` prevents Terraform from overwriting secrets updated via AWS Console or CLI.

### 9. `ecr`
- Container repositories: `${project_name}/backend` and `${project_name}/frontend`.
- Image vulnerability scanning on push.
- Lifecycle rules: purges untagged images after 14 days and retains the latest 20 images.

### 10. `stage_scheduler` (Stage Only)
- Python 3.11 Lambda function triggered by AWS EventBridge cron schedules.
- Nightly Stop (`15:30 UTC` / `9:00 PM IST`): Scales ECS services to 0 and stops the RDS DB instance.
- Morning Start (`03:30 UTC` / `9:00 AM IST`): Starts the RDS DB instance and scales ECS services back to desired count.
- Saves **50-70%** of staging cloud costs every month.

---

## 5. Deployment Instructions

### Prerequisites
1. [AWS CLI v2](https://aws.amazon.com/cli/) configured (`aws configure`).
2. [Terraform >= 1.5.0](https://developer.hashicorp.com/terraform/downloads).

### Step 1: Initialize Stage Environment
```bash
cd terraform/environments/stage

# Inspect or adjust values in terraform.tfvars
cat terraform.tfvars

# Initialize Terraform (downloads AWS provider and connects modules)
terraform init

# Validate configuration
terraform validate

# Review proposed infrastructure changes
terraform plan

# Apply infrastructure
terraform apply
```

### Step 2: Initialize Production Environment
```bash
cd terraform/environments/prod

# Inspect or adjust values in terraform.tfvars
cat terraform.tfvars

terraform init
terraform validate
terraform plan
terraform apply
```

### Step 3: Populate Secrets Manager
After provisioning, populate your application credentials in AWS Secrets Manager:
```bash
aws secretsmanager put-secret-value \
  --region eu-central-1 \
  --secret-id "estateos/stage/backend" \
  --secret-string '{
    "OPENAI_API_KEY": "sk-...",
    "GEMINI_API_KEY": "AI...",
    "GROQ_API_KEY": "gsk_...",
    "LANGFUSE_PUBLIC_KEY": "pk-...",
    "LANGFUSE_SECRET_KEY": "sk-...",
    "DASHBOARD_SESSION_SECRET": "your-secure-32-character-session-secret",
    "WHATSAPP_ACCESS_TOKEN": "...",
    "WHATSAPP_PHONE_NUMBER_ID": "...",
    "WHATSAPP_APP_SECRET": "...",
    "WHATSAPP_VERIFY_TOKEN": "..."
  }'
```

### Step 4: Run Initial Database Migration
Once container images are pushed to ECR, run the one-shot Alembic migration task:
```bash
aws ecs run-task \
  --region eu-central-1 \
  --cluster estateos-stage-cluster \
  --task-definition estateos-stage-migrator \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<SUBNET_ID>],securityGroups=[<ECS_SG_ID>],assignPublicIp=ENABLED}"
```

