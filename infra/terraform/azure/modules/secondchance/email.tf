# FR-026: mission emails leave from one Azure-managed sender domain (Azure Communication Services Email).
# The in-app notification is always written; e-mail is the second channel. The notifier looks the address up
# in Microsoft Graph by object id and sends with its managed identity: no connection string exists.
# A custom domain needs DNS records Terraform cannot publish for you; see docs/deployment-azure.md.

resource "azurerm_email_communication_service" "main" {
  name                = "acse-${var.name}-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  data_location       = "Europe"
  tags                = local.tags
}

resource "azurerm_email_communication_service_domain" "managed" {
  name              = "AzureManagedDomain"
  email_service_id  = azurerm_email_communication_service.main.id
  domain_management = "AzureManaged"
  tags              = local.tags
}

resource "azurerm_communication_service" "main" {
  name                = "acs-${var.name}-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  data_location       = "Europe"
  tags                = local.tags
}

resource "azurerm_communication_service_email_domain_association" "main" {
  communication_service_id = azurerm_communication_service.main.id
  email_service_domain_id  = azurerm_email_communication_service_domain.managed.id
}

locals {
  mail_sender       = "${var.notification_sender_username}@${azurerm_email_communication_service_domain.managed.mail_from_sender_domain}"
  acs_endpoint      = "https://${azurerm_communication_service.main.hostname}"
  notification_from = local.mail_sender
}
