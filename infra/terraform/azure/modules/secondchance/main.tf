# SecondChance on Azure (ADR-023): the same logical architecture as the AWS module, with the Azure
# services in the same places. One file per area, like modules/secondchance for AWS:
#   network, data (PostgreSQL), storage, queues (Service Bus), ai, realtime (Web PubSub), email (ACS),
#   identity (managed identities, Entra apps, role assignments), compute (Container Apps), edge (Front Door),
#   detection, observability.
# There is no secret anywhere in this configuration: every service accepts only Entra tokens.

data "azurerm_client_config" "current" {}
data "azuread_client_config" "current" {}

locals {
  tenant_id       = data.azurerm_client_config.current.tenant_id
  subscription_id = data.azurerm_client_config.current.subscription_id

  # Globally unique names derive from the subscription, so a destroyed environment can be rebuilt
  # under the same names and two subscriptions never collide.
  suffix  = substr(sha256("${local.subscription_id}/${var.name}"), 0, 6)
  compact = replace(var.name, "-", "")

  tags = { project = "secondchance", environment = var.environment, managed_by = "terraform" }

  is_pilot = var.environment == "pilot"

  oidc_issuer    = var.oidc_issuer != "" ? var.oidc_issuer : "https://${var.entra_authority_host}/${local.tenant_id}/v2.0"
  oidc_jwks_uri  = var.oidc_jwks_uri != "" ? var.oidc_jwks_uri : "https://${var.entra_authority_host}/${local.tenant_id}/discovery/v2.0/keys"
  oidc_client_id = var.create_app_registrations ? azuread_application.web[0].client_id : var.oidc_client_id
  web_origin     = "https://${azurerm_cdn_frontdoor_endpoint.main.host_name}"
}

resource "terraform_data" "inputs" {
  lifecycle {
    precondition {
      condition     = var.create_app_registrations || var.oidc_client_id != ""
      error_message = "Without create_app_registrations, pass the existing app registration's oidc_client_id."
    }
    precondition {
      condition     = var.postgres_high_availability ? !startswith(var.postgres_sku_name, "B_") : true
      error_message = "Zone-redundant high availability needs a General Purpose or Memory Optimized SKU, not Burstable."
    }
    precondition {
      condition     = var.web_pubsub_sku != "Free_F1" || !local.is_pilot
      error_message = "The Free Web PubSub tier allows 20 concurrent connections: use Standard_S1 for the pilot."
    }
  }
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.name}"
  location = var.location
  tags     = local.tags
}

# Role assignments take a while to reach the data planes; a container that starts before AcrPull is effective
# cannot pull its image and the revision stays failed. The managed-identity service also caches a token per
# resource for up to 24 hours: a container that asked for a gateway token before the app role was granted would
# keep a token without the role, so the apps start only after every assignment, Entra's included, has been made.
resource "time_sleep" "role_propagation" {
  create_duration = "60s"
  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.servicebus,
    azurerm_role_assignment.scaler,
    azurerm_role_assignment.objects,
    azurerm_role_assignment.table,
    azurerm_role_assignment.ai,
    azurerm_role_assignment.pubsub,
    azurerm_role_assignment.email,
    azurerm_role_assignment.telemetry,
    azuread_app_role_assignment.service,
    azuread_app_role_assignment.notifier_graph,
  ]
}
