# Pilot with real data: Multi-AZ, deletion protection, longer backups. Before the first apply:
# DPIA done, DPA signed, cost review approved (docs/compliance/gdpr.md section 12).

terraform {
  required_version = ">= 1.16"
  required_providers {
    aws  = { source = "hashicorp/aws", version = "~> 6.66" }
    http = { source = "hashicorp/http", version = "~> 3.5" }
  }
  backend "s3" {
    key          = "secondchance/pilot/terraform.tfstate"
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

locals {
  tags = { project = "secondchance", environment = "pilot", managed_by = "terraform" }
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

  name                     = "secondchance-pilot"
  environment              = "pilot"
  image_tag                = var.image_tag
  alarm_email              = var.alarm_email
  aurora_min_acu           = 0.5 # no pause: no cold start for operators (PRD section 12)
  aurora_max_acu           = 8
  aurora_instances         = 2 # writer + reader in the second AZ
  backup_retention_days    = 14
  deletion_protection      = true
  force_destroy            = false
  api_reserved_concurrency = 20
  monthly_budget_usd       = 150
}

output "web_url" { value = module.secondchance.web_url }
output "ecr_repository_url" { value = module.secondchance.ecr_repository_url }
output "migrate_function" { value = module.secondchance.migrate_function }
output "web_bucket" { value = module.secondchance.web_bucket }
output "distribution_id" { value = module.secondchance.distribution_id }
output "user_pool_id" { value = module.secondchance.user_pool_id }
output "hosted_ui_domain" { value = module.secondchance.hosted_ui_domain }
