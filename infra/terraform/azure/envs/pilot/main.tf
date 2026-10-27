# Pilot with real data: zone-redundant database, locks, a known outbound address, longer backups. Before the
# first apply: DPIA done, DPA signed, cost review approved (docs/compliance/gdpr.md section 12). The defaults
# below are the smallest production-shaped choice; the two expensive upgrades (Premium Front Door for the
# managed WAF rule sets, Premium Service Bus for private queues) are variables, with their price in
# docs/deployment-azure.md.

terraform {
  required_version = ">= 1.16"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.81" }
    azuread = { source = "hashicorp/azuread", version = "~> 3.10" }
    time    = { source = "hashicorp/time", version = "~> 0.13" }
  }
  backend "azurerm" {
    key              = "secondchance/pilot/terraform.tfstate"
    use_azuread_auth = true
  }
}

variable "subscription_id" {
  type = string
}

variable "image_tag" {
  type = string
}

variable "alarm_email" {
  type = string
}

variable "location" {
  type    = string
  default = "germanywestcentral"
}

variable "front_door_sku" {
  type    = string
  default = "Standard_AzureFrontDoor"
}

variable "servicebus_sku" {
  type    = string
  default = "Standard"
}

variable "postgres_sku_name" {
  type    = string
  default = "GP_Standard_D2ds_v5"
}

variable "monthly_budget" {
  type    = number
  default = 450
}

variable "chat_model" {
  type = object({ name = string, version = string, sku = string, capacity = number })
  default = {
    name     = "gpt-4.1-mini"
    version  = "2025-04-14"
    sku      = "DataZoneStandard"
    capacity = 50
  }
}

variable "embedding_model" {
  type = object({ name = string, version = string, sku = string, capacity = number })
  default = {
    name     = "text-embedding-3-large"
    version  = "1"
    sku      = "DataZoneStandard"
    capacity = 50
  }
}

variable "create_app_registrations" {
  type    = bool
  default = true
}

variable "oidc_client_id" {
  type    = string
  default = ""
}

variable "oidc_issuer" {
  type        = string
  default     = ""
  description = "Entra External ID issuer for public self-service sign-up (docs/deployment-azure.md)"
}

variable "oidc_jwks_uri" {
  type    = string
  default = ""
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true

  features {
    resource_group {
      prevent_deletion_if_contains_resources = true # a stray resource must be looked at, not swept away
    }
    cognitive_account {
      purge_soft_delete_on_destroy = false
    }
  }
}

provider "azuread" {}

module "secondchance" {
  source = "../../modules/secondchance"

  name        = "secondchance-pilot"
  environment = "pilot"
  location    = var.location
  image_tag   = var.image_tag
  alarm_email = var.alarm_email

  create_app_registrations = var.create_app_registrations
  oidc_client_id           = var.oidc_client_id
  oidc_issuer              = var.oidc_issuer
  oidc_jwks_uri            = var.oidc_jwks_uri

  chat_model      = var.chat_model
  embedding_model = var.embedding_model

  front_door_sku             = var.front_door_sku
  servicebus_sku             = var.servicebus_sku
  web_pubsub_sku             = "Standard_S1"
  postgres_sku_name          = var.postgres_sku_name
  postgres_high_availability = true
  postgres_storage_mb        = 65536
  backup_retention_days      = 14
  geo_redundant_backup       = true
  storage_replication        = "ZRS"
  deletion_protection        = true
  zone_redundant             = true
  nat_gateway                = true
  acr_sku                    = "Standard"
  monthly_budget             = var.monthly_budget

  api_min_replicas     = 1 # no cold start for operators (PRD section 12)
  gateway_min_replicas = 1
  worker_min_replicas  = 0
  requeue_cron         = "*/2 * * * *"

  max_replicas    = { api = 10, jobs = 4, agents = 4, notifier = 2, gateway = 4, executor = 4, web = 3 }
  db_pool_size    = 5
  db_max_overflow = 3
}

output "web_url" { value = module.secondchance.web_url }
output "resource_group" { value = module.secondchance.resource_group }
output "registry_name" { value = module.secondchance.registry_name }
output "registry_login_server" { value = module.secondchance.registry_login_server }
output "front_door_id" { value = module.secondchance.front_door_id }
output "tenant_id" { value = module.secondchance.tenant_id }
output "oidc_client_id" { value = module.secondchance.oidc_client_id }
output "database_host" { value = module.secondchance.database_host }
output "servicebus_namespace" { value = module.secondchance.servicebus_namespace }
output "notification_sender" { value = module.secondchance.notification_sender }
output "apps" { value = module.secondchance.apps }
output "jobs" { value = module.secondchance.jobs }
output "web_pubsub_endpoint" { value = module.secondchance.web_pubsub_endpoint }
