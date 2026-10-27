# Azure Database for PostgreSQL flexible server (ADR-001, ADR-004 on Azure): RLS, pgvector, PostGIS, FTS.
# Password authentication is off: the three database roles and the database itself are created by the bootstrap
# job (python -m secondchance.azure_entry bootstrap), which runs as the server's Entra administrator and maps
# each role to a managed identity.

locals {
  # Planning values, deliberately below what each tier allows (Microsoft's defaults grow with memory).
  postgres_connection_ceiling = coalesce(var.postgres_max_connections, lookup({
    "B_Standard_B1ms"     = 50
    "B_Standard_B2s"      = 100
    "GP_Standard_D2ds_v5" = 400
    "GP_Standard_D4ds_v5" = 800
  }, var.postgres_sku_name, 50))

  # Every process that opens the application database pool, at its maximum scale-out (ADR-006).
  db_client_processes = var.max_replicas.api + var.max_replicas.jobs + var.max_replicas.agents + var.max_replicas.executor
  db_connections_peak = local.db_client_processes * (var.db_pool_size + var.db_max_overflow)

  db_host = azurerm_postgresql_flexible_server.main.fqdn
  db_url = {
    for role in ["secondchance_app", "secondchance_migrator", "secondchance_maintenance"] :
    role => "postgresql+psycopg://${role}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/secondchance"
  }
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.name}.private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-postgres"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.main.id
  tags                  = local.tags
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "psql-${var.name}-${local.suffix}"
  location                      = azurerm_resource_group.main.location
  resource_group_name           = azurerm_resource_group.main.name
  version                       = var.postgres_version
  sku_name                      = var.postgres_sku_name
  storage_mb                    = var.postgres_storage_mb
  auto_grow_enabled             = true
  backup_retention_days         = var.backup_retention_days
  geo_redundant_backup_enabled  = var.geo_redundant_backup
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  zone                          = "1"
  tags                          = local.tags

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = local.tenant_id
  }

  dynamic "high_availability" {
    for_each = var.postgres_high_availability ? [1] : []
    content {
      mode                      = "ZoneRedundant"
      standby_availability_zone = "2"
    }
  }

  maintenance_window {
    day_of_week  = 0 # Sunday, 03:00 UTC: after the nightly retention job
    start_hour   = 3
    start_minute = 30
  }

  lifecycle {
    # After a failover the primary and the standby swap zones; Terraform must not move them back.
    ignore_changes = [zone, high_availability[0].standby_availability_zone]

    precondition {
      condition     = local.db_connections_peak <= floor(local.postgres_connection_ceiling * 0.8)
      error_message = "At full scale-out the containers could open ${local.db_connections_peak} connections (replicas x (pool + overflow)), more than 80% of the ${local.postgres_connection_ceiling} the ${var.postgres_sku_name} tier is planned for. Lower max_replicas or the pool, or choose a larger SKU (ADR-006)."
    }
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

# Extensions must be allow-listed before CREATE EXTENSION works; the bootstrap job then creates them.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "POSTGIS,VECTOR"
}

# The identity that bootstraps the roles. It is administrator of the server and is used by one job only.
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "bootstrap" {
  server_name         = azurerm_postgresql_flexible_server.main.name
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = local.tenant_id
  object_id           = azurerm_user_assigned_identity.main["dbadmin"].principal_id
  principal_name      = azurerm_user_assigned_identity.main["dbadmin"].name
  principal_type      = "ServicePrincipal"

  depends_on = [azurerm_postgresql_flexible_server_configuration.extensions]
}

resource "azurerm_management_lock" "database" {
  count      = var.deletion_protection ? 1 : 0
  name       = "protect-database"
  scope      = azurerm_postgresql_flexible_server.main.id
  lock_level = "CanNotDelete"
  notes      = "Remove deliberately before destroying the pilot"
}
