# jobs, notify and agents, each dead-lettering after 5 deliveries (ADR-005, ADR-011, ADR-023). Messages hold
# identifiers only. The agents queue replaces the Step Functions execution of AWS: the run state, leases and
# budgets live in PostgreSQL either way, and the requeue job restarts anything a crashed worker left.

locals {
  queues = {
    jobs   = { lock_duration = "PT5M" } # a long handler renews its lock; 5 minutes is Service Bus's ceiling
    notify = { lock_duration = "PT5M" }
    agents = { lock_duration = "PT5M" }
  }
}

resource "azurerm_servicebus_namespace" "main" {
  name                          = "sb-${var.name}-${local.suffix}"
  location                      = azurerm_resource_group.main.location
  resource_group_name           = azurerm_resource_group.main.name
  sku                           = var.servicebus_sku
  capacity                      = var.servicebus_sku == "Premium" ? 1 : 0
  premium_messaging_partitions  = var.servicebus_sku == "Premium" ? 1 : 0
  local_auth_enabled            = false # no connection strings, no keys: Entra tokens only
  minimum_tls_version           = "1.2"
  public_network_access_enabled = var.servicebus_sku != "Premium"
  tags                          = local.tags

  dynamic "network_rule_set" {
    for_each = var.servicebus_sku == "Premium" ? [1] : []
    content {
      default_action                = "Deny"
      public_network_access_enabled = false
      trusted_services_allowed      = true
    }
  }
}

resource "azurerm_servicebus_queue" "main" {
  for_each     = local.queues
  name         = each.key
  namespace_id = azurerm_servicebus_namespace.main.id

  lock_duration                        = each.value.lock_duration
  max_delivery_count                   = 5 # then the broker moves the message to the dead-letter sub-queue
  dead_lettering_on_message_expiration = true
  default_message_ttl                  = "P4D" # SQS retention on AWS
  max_size_in_megabytes                = 1024
  requires_duplicate_detection         = false
  batched_operations_enabled           = true
}
