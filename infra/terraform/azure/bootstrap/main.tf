# Once per subscription, by a person who may grant Entra application permissions (Global Administrator or
# Privileged Role Administrator for the two Graph roles below) and own the subscription:
#   - the Terraform state: a private storage account, Entra authentication only, versioned
#   - the deployment identity, trusted by this GitHub repository's 'production' environment through a
#     federated credential, so no Azure secret is ever stored in GitHub (ADR-018)
# Local state on purpose: it holds no secret and can be recreated by importing three resources.
#
# The deployment identity can create every resource and every role assignment of the environments, which
# makes it as powerful as the subscription: use a subscription dedicated to SecondChance (the same advice
# the AWS bootstrap gives for the account), and require a reviewer on the GitHub environment.

terraform {
  required_version = ">= 1.16"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.81" }
    azuread = { source = "hashicorp/azuread", version = "~> 3.10" }
  }
}

variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "germanywestcentral"
}

variable "github_repository" {
  type        = string
  default     = ""
  description = "owner/name; empty skips the federated credential (deploying from a workstation only)"
  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "owner/name"
  }
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
  features {}
}

provider "azuread" {}

data "azurerm_client_config" "current" {}
data "azurerm_subscription" "current" {}
data "azuread_client_config" "current" {}

locals {
  tags   = { project = "secondchance", purpose = "terraform-state", managed_by = "terraform" }
  suffix = substr(sha256(var.subscription_id), 0, 8)
}

# --- state ---------------------------------------------------------------------------------------

resource "azurerm_resource_group" "state" {
  name     = "rg-secondchance-tfstate"
  location = var.location
  tags     = local.tags
}

# The state holds no secret (nothing in the configuration is one), but it is infrastructure truth.
# CI reaches it from the Internet, so the endpoint is public and every request needs an Entra token.
# trivy:ignore:AVD-AZU-0012
resource "azurerm_storage_account" "state" {
  name                            = "sctfstate${local.suffix}"
  location                        = azurerm_resource_group.state.location
  resource_group_name             = azurerm_resource_group.state.name
  account_tier                    = "Standard"
  account_replication_type        = "GRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  tags                            = local.tags

  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

resource "azurerm_management_lock" "state" {
  name       = "protect-state"
  scope      = azurerm_storage_account.state.id
  lock_level = "CanNotDelete"
  notes      = "Terraform state of every SecondChance environment"
}

# Whoever runs this bootstrap keeps working with the state afterwards.
resource "azurerm_role_assignment" "state_operator" {
  scope              = azurerm_storage_account.state.id
  role_definition_id = "${azurerm_storage_account.state.id}/providers/Microsoft.Authorization/roleDefinitions/ba92f5b4-2d11-453d-a403-e96b0029c9fe" # Storage Blob Data Contributor
  principal_id       = data.azurerm_client_config.current.object_id
}

# --- deployment identity ---------------------------------------------------------------------------

resource "azuread_application" "deploy" {
  display_name = "secondchance-deploy"
  owners       = [data.azuread_client_config.current.object_id]
}

resource "azuread_service_principal" "deploy" {
  client_id = azuread_application.deploy.client_id
  owners    = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_federated_identity_credential" "github" {
  count          = var.github_repository == "" ? 0 : 1
  application_id = azuread_application.deploy.id
  display_name   = "github-production"
  description    = "Deployments approved in the repository's production environment"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repository}:environment:production"
}

resource "azurerm_role_assignment" "deploy" {
  for_each = {
    "Contributor"               = "b24988ac-6180-42a0-ab88-20f7382dd24c"
    "User Access Administrator" = "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9"
  }
  scope              = data.azurerm_subscription.current.id
  role_definition_id = "${data.azurerm_subscription.current.id}/providers/Microsoft.Authorization/roleDefinitions/${each.value}"
  principal_id       = azuread_service_principal.deploy.object_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "deploy_state" {
  scope              = azurerm_storage_account.state.id
  role_definition_id = "${azurerm_storage_account.state.id}/providers/Microsoft.Authorization/roleDefinitions/ba92f5b4-2d11-453d-a403-e96b0029c9fe" # Storage Blob Data Contributor
  principal_id       = azuread_service_principal.deploy.object_id
  principal_type     = "ServicePrincipal"
}

# What the environments ask Entra to do: create their own app registrations (and only those: OwnedBy),
# and grant app roles to their managed identities (gateway, tool executor, Graph User.Read.All).
data "azuread_application_published_app_ids" "well_known" {}

resource "azuread_service_principal" "msgraph" {
  client_id    = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  use_existing = true
}

resource "azuread_app_role_assignment" "deploy_graph" {
  for_each            = toset(["Application.ReadWrite.OwnedBy", "AppRoleAssignment.ReadWrite.All"])
  app_role_id         = azuread_service_principal.msgraph.app_role_ids[each.value]
  principal_object_id = azuread_service_principal.deploy.object_id
  resource_object_id  = azuread_service_principal.msgraph.object_id
}

# --- outputs ---------------------------------------------------------------------------------------

output "state_resource_group" { value = azurerm_resource_group.state.name }
output "state_storage_account" { value = azurerm_storage_account.state.name }
output "state_container" { value = azurerm_storage_container.state.name }
output "tenant_id" { value = data.azurerm_client_config.current.tenant_id }
output "subscription_id" { value = var.subscription_id }
output "deploy_client_id" {
  description = "AZURE_CLIENT_ID for the GitHub environment (variables AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID)"
  value       = azuread_application.deploy.client_id
}
