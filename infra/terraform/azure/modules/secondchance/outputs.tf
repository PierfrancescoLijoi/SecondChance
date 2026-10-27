output "resource_group" {
  value = azurerm_resource_group.main.name
}

output "web_url" {
  value = local.web_origin
}

output "registry_name" {
  value = azurerm_container_registry.main.name
}

output "registry_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "front_door_profile" {
  value = azurerm_cdn_frontdoor_profile.main.name
}

output "front_door_id" {
  description = "The profile id the containers expect in X-Azure-FDID"
  value       = azurerm_cdn_frontdoor_profile.main.resource_guid
}

output "tenant_id" {
  value = local.tenant_id
}

output "oidc_client_id" {
  value = local.oidc_client_id
}

output "oidc_issuer" {
  value = local.oidc_issuer
}

output "database_host" {
  value = local.db_host
}

output "servicebus_namespace" {
  value = azurerm_servicebus_namespace.main.name
}

output "storage_account" {
  value = azurerm_storage_account.objects.name
}

output "web_pubsub_endpoint" {
  value = local.web_pubsub_endpoint
}

output "notification_sender" {
  description = "Azure-managed sender of mission emails (FR-026); no verification step is needed"
  value       = local.mail_sender
}

output "openai_endpoint" {
  value = local.openai_endpoint
}

output "chat_deployment" {
  value = var.llm_mode == "azure_openai" ? azurerm_cognitive_deployment.chat[0].name : null
}

output "embedding_deployment" {
  value = azurerm_cognitive_deployment.embedding.name
}

output "apps" {
  description = "Container App names by role"
  value       = { for key, app in azurerm_container_app.main : key => app.name }
}

output "jobs" {
  description = "Container Apps job names by task (bootstrap, migrate, retention, requeue, check, and seed/tools in the demo)"
  value       = { for key, job in azurerm_container_app_job.main : key => job.name }
}

output "schedules" {
  value = { retention = local.jobs["retention"].trigger, requeue = local.jobs["requeue"].trigger }
}

output "database_connection_budget" {
  description = "Peak connections the replica limits allow against the planned ceiling (ADR-006)"
  value       = { peak = local.db_connections_peak, ceiling = local.postgres_connection_ceiling }
}

output "identities" {
  description = "Client ids of the managed identities, for operators and tests"
  value       = { for key, identity in azurerm_user_assigned_identity.main : key => identity.client_id }
}

output "app_identities" {
  description = "The managed identities each Container App holds besides the image-pull one (least privilege, identity.tf)"
  value       = { for key, app in local.apps : key => app.identities }
}
