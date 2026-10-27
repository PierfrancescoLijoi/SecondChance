# Real-time run progress (ADR-023). Azure Web PubSub replaces API Gateway WebSocket + DynamoDB + the
# publisher Lambda: the API checks membership and ownership and mints a short-lived URL whose token joins
# one group (run-<id>) and grants no send or join right; workers publish to that group. Keys are off, so
# only Entra identities can publish or mint tokens. Browsers connect directly, hence the public endpoint.

resource "azurerm_web_pubsub" "main" {
  name                          = "wps-${var.name}-${local.suffix}"
  location                      = azurerm_resource_group.main.location
  resource_group_name           = azurerm_resource_group.main.name
  sku                           = var.web_pubsub_sku
  capacity                      = 1
  local_auth_enabled            = false
  aad_auth_enabled              = true
  public_network_access_enabled = true
  tls_client_cert_enabled       = false
  tags                          = local.tags
}

resource "azurerm_web_pubsub_hub" "runs" {
  name                          = "runs"
  web_pubsub_id                 = azurerm_web_pubsub.main.id
  anonymous_connections_enabled = false
}

locals {
  web_pubsub_endpoint = "https://${azurerm_web_pubsub.main.hostname}"
}
