# Ephemeral demo with synthetic data (NFR-023): created and destroyed with one command.
# Backend values come from scripts/deploy.sh (-backend-config), never from this file.

terraform {
  required_version = ">= 1.16"
  required_providers {
    aws  = { source = "hashicorp/aws", version = "~> 6.66" }
    http = { source = "hashicorp/http", version = "~> 3.5" }
  }
  backend "s3" {
    key          = "secondchance/demo/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

variable "image_tag" {
  type = string
}

variable "alarm_email" {
  type = string
}

variable "notification_sender_email" {
  type        = string
  default     = ""
  description = "SES sender of mission emails; empty uses alarm_email"
}

locals {
  tags = { project = "secondchance", environment = "demo", managed_by = "terraform" }
}

provider "aws" {
  region = "eu-central-1"
  default_tags {
    tags = local.tags
  }
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = local.tags
  }
}

module "secondchance" {
  source    = "../../modules/secondchance"
  providers = { aws = aws, aws.us_east_1 = aws.us_east_1, http = http }

  name        = "secondchance-demo"
  environment = "demo"
  image_tag   = var.image_tag
  alarm_email = var.alarm_email

  notification_sender_email = var.notification_sender_email
  aurora_min_acu            = 0 # requested; RDS Proxy keeps the instance awake (docs/deployment.md)
  aurora_max_acu            = 2
  aurora_instances          = 1
  deletion_protection       = false
  force_destroy             = true
  monthly_budget_usd        = 30

  # New accounts start at 10 concurrent executions and Lambda keeps 100 unreserved: reserve nothing.
  api_reserved_concurrency         = null
  mcp_gateway_reserved_concurrency = null
  requeue_schedule                 = "rate(1 hour)" # fewer database wake-ups in an idle demo
}

output "web_url" { value = module.secondchance.web_url }
output "ecr_repository_url" { value = module.secondchance.ecr_repository_url }
output "migrate_function" { value = module.secondchance.migrate_function }
output "web_bucket" { value = module.secondchance.web_bucket }
output "distribution_id" { value = module.secondchance.distribution_id }
output "user_pool_id" { value = module.secondchance.user_pool_id }
output "hosted_ui_domain" { value = module.secondchance.hosted_ui_domain }
output "notification_sender" { value = module.secondchance.notification_sender }
