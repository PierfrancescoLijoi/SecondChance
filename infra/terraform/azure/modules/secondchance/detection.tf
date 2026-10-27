# Detective controls (ADR-022, GDPR art. 32): Defender for Storage scans every upload for malware and writes
# its verdict to the blob's index tag, which the jobs worker reads before parsing (storage.scan_status);
# the application identity cannot write that tag (storage.tf). Who read or wrote which tenant document is
# the storage account's blob log, kept in the Log Analytics workspace for the same period as the AWS trail.
# Defender for Cloud's wider plans (servers, databases, containers) are a subscription-level choice and are
# deliberately not switched on from inside one environment.

resource "azurerm_security_center_storage_defender" "objects" {
  count                                       = var.defender_malware_scanning ? 1 : 0
  storage_account_id                          = azurerm_storage_account.objects.id
  override_subscription_settings_enabled      = true
  malware_scanning_on_upload_enabled          = true
  malware_scanning_on_upload_cap_gb_per_month = var.malware_scan_cap_gb_per_month
  sensitive_data_discovery_enabled            = false
}

resource "azurerm_monitor_diagnostic_setting" "documents" {
  name                       = "to-log-analytics"
  target_resource_id         = "${azurerm_storage_account.objects.id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "StorageRead"
  }
  enabled_log {
    category = "StorageWrite"
  }
  enabled_log {
    category = "StorageDelete"
  }
}
