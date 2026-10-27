# One virtual network, three subnets (ADR-006 on Azure): the Container Apps environment, PostgreSQL
# (delegated, no public endpoint) and the private endpoints of the PaaS services that hold data.
# Service Bus joins them in the Premium tier. Web PubSub stays public by design: browsers connect to it.

resource "azurerm_virtual_network" "main" {
  name                = "vnet-${var.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = [var.vnet_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "aca" {
  name                 = "snet-aca"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 7, 0)] # /23, the size Microsoft recommends for the environment

  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 8, 2)]

  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "endpoints" {
  name                              = "snet-endpoints"
  resource_group_name               = azurerm_resource_group.main.name
  virtual_network_name              = azurerm_virtual_network.main.name
  address_prefixes                  = [cidrsubnet(var.vnet_cidr, 8, 3)]
  private_endpoint_network_policies = "Enabled" # the NSG below applies to private endpoints too
}

# --- network security group of the private endpoints ---------------------------------------------
# There is none on the Container Apps subnet: Microsoft documents that inbound traffic of an external
# workload-profile environment enters through its public address, not through the subnet, so an NSG there
# cannot restrict it. The origin lock is the X-Azure-FDID check (secondchance.edge, the web container).

resource "azurerm_network_security_group" "endpoints" {
  name                = "nsg-${var.name}-endpoints"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags

  security_rule {
    name                       = "AllowServicesFromContainerApps"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["443", "5671"] # HTTPS, and AMQP over TLS for Service Bus Premium
    source_address_prefix      = azurerm_subnet.aca.address_prefixes[0]
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "DenyOtherInbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "endpoints" {
  subnet_id                 = azurerm_subnet.endpoints.id
  network_security_group_id = azurerm_network_security_group.endpoints.id
}

# --- explicit outbound address (pilot) ---------------------------------------------------------

resource "azurerm_public_ip" "nat" {
  count               = var.nat_gateway ? 1 : 0
  name                = "pip-${var.name}-nat"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = ["1", "2", "3"]
  tags                = local.tags
}

resource "azurerm_nat_gateway" "main" {
  count               = var.nat_gateway ? 1 : 0
  name                = "ng-${var.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku_name            = "Standard"
  tags                = local.tags
}

resource "azurerm_nat_gateway_public_ip_association" "main" {
  count                = var.nat_gateway ? 1 : 0
  nat_gateway_id       = azurerm_nat_gateway.main[0].id
  public_ip_address_id = azurerm_public_ip.nat[0].id
}

resource "azurerm_subnet_nat_gateway_association" "aca" {
  count          = var.nat_gateway ? 1 : 0
  subnet_id      = azurerm_subnet.aca.id
  nat_gateway_id = azurerm_nat_gateway.main[0].id
}

# --- private DNS and endpoints ------------------------------------------------------------------

locals {
  private_zones = {
    blob       = "privatelink.blob.core.windows.net"
    table      = "privatelink.table.core.windows.net"
    openai     = "privatelink.openai.azure.com"
    cognitive  = "privatelink.cognitiveservices.azure.com"
    foundry    = "privatelink.services.ai.azure.com"
    servicebus = "privatelink.servicebus.windows.net"
  }
  servicebus_private = var.servicebus_sku == "Premium"
  zones_in_use       = { for key, zone in local.private_zones : key => zone if key != "servicebus" || local.servicebus_private }

  private_endpoints = merge(
    {
      blob  = { resource = azurerm_storage_account.objects.id, subresource = "blob", zones = ["blob"] }
      table = { resource = azurerm_storage_account.objects.id, subresource = "table", zones = ["table"] }
      ai    = { resource = azurerm_cognitive_account.ai.id, subresource = "account", zones = ["openai", "cognitive", "foundry"] }
    },
    local.servicebus_private ? {
      servicebus = { resource = azurerm_servicebus_namespace.main.id, subresource = "namespace", zones = ["servicebus"] }
    } : {}
  )
}

resource "azurerm_private_dns_zone" "main" {
  for_each            = local.zones_in_use
  name                = each.value
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "main" {
  for_each              = local.zones_in_use
  name                  = "link-${each.key}"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.main[each.key].name
  virtual_network_id    = azurerm_virtual_network.main.id
  tags                  = local.tags
}

resource "azurerm_private_endpoint" "main" {
  for_each            = local.private_endpoints
  name                = "pe-${var.name}-${each.key}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  subnet_id           = azurerm_subnet.endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = each.key
    private_connection_resource_id = each.value.resource
    subresource_names              = [each.value.subresource]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [for zone in each.value.zones : azurerm_private_dns_zone.main[zone].id]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.main]
}
