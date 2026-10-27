# One storage account: the tenant documents (blobs under tenants/{id}/, ADR-011) and the small table the
# MCP gateway counts its rate limits in. Shared keys are off: every caller is an Entra identity, and the
# only network path is the private endpoint (plus Azure's own trusted services, which Defender for
# Storage needs to scan uploads).

resource "azurerm_storage_account" "objects" {
  name                              = "${substr(local.compact, 0, 12)}${local.suffix}"
  location                          = azurerm_resource_group.main.location
  resource_group_name               = azurerm_resource_group.main.name
  account_tier                      = "Standard"
  account_kind                      = "StorageV2"
  account_replication_type          = var.storage_replication
  min_tls_version                   = "TLS1_2"
  https_traffic_only_enabled        = true
  allow_nested_items_to_be_public   = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  cross_tenant_replication_enabled  = false
  infrastructure_encryption_enabled = true
  public_network_access_enabled     = true # "selected networks" with none selected: see network_rules
  tags                              = local.tags

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }

  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }
}

resource "azurerm_storage_container" "objects" {
  name                  = "objects"
  storage_account_id    = azurerm_storage_account.objects.id
  container_access_type = "private"
}

resource "azurerm_storage_table" "rate_limit" {
  name               = "ratelimit"
  storage_account_id = azurerm_storage_account.objects.id
}

resource "azurerm_storage_management_policy" "objects" {
  storage_account_id = azurerm_storage_account.objects.id

  rule {
    name    = "housekeeping"
    enabled = true
    filters {
      blob_types = ["blockBlob"]
    }
    actions {
      version {
        delete_after_days_since_creation = 30
      }
    }
  }
}

resource "azurerm_management_lock" "objects" {
  count      = var.deletion_protection ? 1 : 0
  name       = "protect-documents"
  scope      = azurerm_storage_account.objects.id
  lock_level = "CanNotDelete"
  notes      = "Remove deliberately before destroying the pilot"
}

# The application may read and write documents and read their malware verdict, nothing else. In
# particular it cannot write blob index tags, where Defender for Storage records that verdict
# (Microsoft documents that tags are not tamper-proof for anyone who can write them).
resource "azurerm_role_definition" "objects" {
  name               = "${var.name}-objects"
  scope              = azurerm_resource_group.main.id
  description        = "SecondChance: read and write tenant documents, read the malware verdict tag"
  role_definition_id = uuidv5("url", "https://secondchance.invalid/roles/${var.name}-objects")
  assignable_scopes  = [azurerm_resource_group.main.id]

  permissions {
    data_actions = [
      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read",
    ]
  }
}
