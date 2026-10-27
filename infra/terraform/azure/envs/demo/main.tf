# Ephemeral demo with synthetic data (NFR-023): created and destroyed with one command.
# Backend values come from scripts/azure/deploy.sh (-backend-config), never from this file.

terraform {
  required_version = ">= 1.16"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.81" }
    azuread = { source = "hashicorp/azuread", version = "~> 3.10" }
    time    = { source = "hashicorp/time", version = "~> 0.13" }
  }
  backend "azurerm" {
    key              = "secondchance/demo/terraform.tfstate"
    use_azuread_auth = true # no storage account key anywhere
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

variable "chat_model" {
  type = object({ name = string, version = string, sku = string, capacity = number })
  default = {
    name     = "gpt-4.1-mini"
    version  = "2025-04-14"
    sku      = "DataZoneStandard"
    capacity = 30
  }
  description = "Set by scripts/azure/connect.sh from what the subscription's region really offers"
}

variable "embedding_model" {
  type = object({ name = string, version = string, sku = string, capacity = number })
  default = {
    name     = "text-embedding-3-large"
    version  = "1"
    sku      = "DataZoneStandard"
    capacity = 30
  }
}

variable "web_pubsub_sku" {
  type        = string
  default     = "Free_F1"
  description = "Only one Free instance is allowed per subscription: Standard_S1 when another exists"
}

variable "create_app_registrations" {
  type    = bool
  default = true
}

variable "oidc_client_id" {
  type    = string
  default = ""
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none" # scripts/azure/connect.sh registers them, visibly and once
  storage_use_azuread             = true

  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    cognitive_account {
      purge_soft_delete_on_destroy = true # the demo is rebuilt under the same names
    }
  }
}

provider "azuread" {}

module "secondchance" {
  source = "../../modules/secondchance"

  name        = "secondchance-demo"
  environment = "demo"
  location    = var.location
  image_tag   = var.image_tag
  alarm_email = var.alarm_email

  chat_model      = var.chat_model
  embedding_model = var.embedding_model

  create_app_registrations = var.create_app_registrations
  oidc_client_id           = var.oidc_client_id

  web_pubsub_sku      = var.web_pubsub_sku
  acr_sku             = "Basic" # pulls use Entra tokens either way; Standard adds throughput the demo does not need
  monthly_budget      = 100     # Azure has fixed monthly prices (Front Door, the database, Defender): see docs/deployment-azure.md
  deletion_protection = false
  requeue_cron        = "0 * * * *" # fewer database wake-ups in an idle demo
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
