"""Generates the azurerm mock data for terraform test: every resource type the module uses gets an id shaped
like the real Azure resource id, so the provider's own id parsers and validators run during the offline apply."""

import os

SUB = "99999999-8888-7777-6666-555555555555"
RG = f"/subscriptions/{SUB}/resourceGroups/rg-mock"
GUID = "12345678-1234-1234-1234-123456789012"


def p(namespace: str, kind: str, name: str) -> str:
    return f"{RG}/providers/{namespace}/{kind}/{name}"


VNET = p("Microsoft.Network", "virtualNetworks", "vnet-mock")
SA = p("Microsoft.Storage", "storageAccounts", "stmock")
SB = p("Microsoft.ServiceBus", "namespaces", "sb-mock")
AFD = p("Microsoft.Cdn", "profiles", "afd-mock")
LAW = p("Microsoft.OperationalInsights", "workspaces", "log-mock")

RESOURCES = {
    "azurerm_resource_group": {"id": RG, "location": "germanywestcentral"},
    "azurerm_virtual_network": {"id": VNET},
    "azurerm_subnet": {"id": f"{VNET}/subnets/snet-mock"},
    "azurerm_network_security_group": {"id": p("Microsoft.Network", "networkSecurityGroups", "nsg-mock")},
    "azurerm_public_ip": {"id": p("Microsoft.Network", "publicIPAddresses", "pip-mock")},
    "azurerm_nat_gateway": {"id": p("Microsoft.Network", "natGateways", "ng-mock")},
    "azurerm_private_dns_zone": {"id": p("Microsoft.Network", "privateDnsZones", "mock.zone")},
    "azurerm_private_endpoint": {"id": p("Microsoft.Network", "privateEndpoints", "pe-mock")},
    "azurerm_postgresql_flexible_server": {
        "id": p("Microsoft.DBforPostgreSQL", "flexibleServers", "psql-mock"),
        "fqdn": "psql-mock.postgres.database.azure.com",
    },
    "azurerm_storage_account": {"id": SA, "primary_blob_endpoint": "https://stmock.blob.core.windows.net/"},
    "azurerm_storage_container": {"id": f"{SA}/blobServices/default/containers/objects"},
    "azurerm_storage_table": {"id": f"{SA}/tableServices/default/tables/ratelimit"},
    "azurerm_role_definition": {
        "id": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/{GUID}",
        "role_definition_resource_id": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/{GUID}",
    },
    "azurerm_servicebus_namespace": {"id": SB},
    "azurerm_servicebus_queue": {"id": f"{SB}/queues/mockqueue"},
    "azurerm_cognitive_account": {"id": p("Microsoft.CognitiveServices", "accounts", "ai-mock")},
    "azurerm_cognitive_deployment": {"id": p("Microsoft.CognitiveServices", "accounts", "ai-mock") + "/deployments/mock"},
    "azurerm_web_pubsub": {"id": p("Microsoft.SignalRService", "webPubSub", "wps-mock"), "hostname": "wps-mock.webpubsub.azure.com"},
    "azurerm_web_pubsub_hub": {"id": p("Microsoft.SignalRService", "webPubSub", "wps-mock") + "/hubs/runs"},
    "azurerm_email_communication_service": {"id": p("Microsoft.Communication", "emailServices", "acse-mock")},
    "azurerm_email_communication_service_domain": {
        "id": p("Microsoft.Communication", "emailServices", "acse-mock") + "/domains/AzureManagedDomain",
        "mail_from_sender_domain": "mock.azurecomm.net",
        "from_sender_domain": "mock.azurecomm.net",
    },
    "azurerm_communication_service": {
        "id": p("Microsoft.Communication", "communicationServices", "acs-mock"),
        "hostname": "acs-mock.europe.communication.azure.com",
    },
    "azurerm_container_registry": {"id": p("Microsoft.ContainerRegistry", "registries", "acrmock"), "login_server": "acrmock.azurecr.io"},
    "azurerm_container_app_environment": {
        "id": p("Microsoft.App", "managedEnvironments", "cae-mock"),
        "default_domain": "mock.germanywestcentral.azurecontainerapps.io",
    },
    "azurerm_container_app": {"id": p("Microsoft.App", "containerApps", "app-mock")},
    "azurerm_container_app_job": {"id": p("Microsoft.App", "jobs", "job-mock")},
    "azurerm_user_assigned_identity": {
        "id": p("Microsoft.ManagedIdentity", "userAssignedIdentities", "id-mock"),
        "principal_id": GUID, "client_id": GUID, "tenant_id": GUID,
    },
    "azurerm_log_analytics_workspace": {"id": LAW},
    "azurerm_application_insights": {
        "id": p("Microsoft.Insights", "components", "appi-mock"),
        "connection_string": "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://mock.in.applicationinsights.azure.com/",
    },
    "azurerm_monitor_action_group": {"id": p("Microsoft.Insights", "actionGroups", "ag-mock")},
    "azurerm_monitor_metric_alert": {"id": p("Microsoft.Insights", "metricAlerts", "alert-mock")},
    "azurerm_monitor_scheduled_query_rules_alert_v2": {"id": p("Microsoft.Insights", "scheduledQueryRules", "rule-mock")},
    "azurerm_cdn_frontdoor_profile": {"id": AFD, "resource_guid": GUID},
    "azurerm_cdn_frontdoor_endpoint": {"id": f"{AFD}/afdEndpoints/ep-mock", "host_name": "ep-mock.z01.azurefd.net"},
    "azurerm_cdn_frontdoor_origin_group": {"id": f"{AFD}/originGroups/og-mock"},
    "azurerm_cdn_frontdoor_origin": {"id": f"{AFD}/originGroups/og-mock/origins/o-mock"},
    "azurerm_cdn_frontdoor_rule_set": {"id": f"{AFD}/ruleSets/rsmock"},
    "azurerm_cdn_frontdoor_rule": {"id": f"{AFD}/ruleSets/rsmock/rules/rmock"},
    "azurerm_cdn_frontdoor_route": {"id": f"{AFD}/afdEndpoints/ep-mock/routes/r-mock"},
    "azurerm_cdn_frontdoor_firewall_policy": {"id": p("Microsoft.Network", "frontDoorWebApplicationFirewallPolicies", "wafmock")},
    "azurerm_cdn_frontdoor_security_policy": {"id": f"{AFD}/securityPolicies/sp-mock"},
    "azurerm_consumption_budget_resource_group": {"id": f"{RG}/providers/Microsoft.Consumption/budgets/mock"},
    "azurerm_management_lock": {"id": f"{RG}/providers/Microsoft.Authorization/locks/mock"},
    "azurerm_role_assignment": {"id": f"{RG}/providers/Microsoft.Authorization/roleAssignments/{GUID}"},
    "azurerm_postgresql_flexible_server_configuration": {"id": p("Microsoft.DBforPostgreSQL", "flexibleServers", "psql-mock") + "/configurations/azure.extensions"},
    "azurerm_postgresql_flexible_server_active_directory_administrator": {"id": p("Microsoft.DBforPostgreSQL", "flexibleServers", "psql-mock") + f"/administrators/{GUID}"},
    "azurerm_security_center_storage_defender": {"id": f"{SA}/providers/Microsoft.Security/defenderForStorageSettings/current"},
    "azurerm_storage_management_policy": {"id": f"{SA}/managementPolicies/default"},
}

out = [
    "# Generated by tests/gen_mocks.py -- do not edit. Resource ids are shaped like real Azure ids so that",
    "# the provider's own id parsers and validators run during the offline apply of the module tests.",
    "",
    'mock_data "azurerm_client_config" {',
    "  defaults = {",
    '    tenant_id       = "11111111-2222-3333-4444-555555555555"',
    f'    subscription_id = "{SUB}"',
    f'    client_id       = "{GUID}"',
    f'    object_id       = "{GUID}"',
    "  }",
    "}",
    "",
]
for name, values in RESOURCES.items():
    out.append(f'mock_resource "{name}" {{')
    out.append("  defaults = {")
    width = max(len(key) for key in values)  # terraform fmt aligns the equals signs
    for key, value in values.items():
        out.append(f'    {key.ljust(width)} = "{value}"')
    out.append("  }")
    out.append("}")
    out.append("")

target = os.path.join(os.path.dirname(__file__), "mocks", "azurerm", "azurerm.tfmock.hcl")
open(target, "w", encoding="utf-8", newline="\n").write("\n".join(out))
print("written", target, len(RESOURCES), "resource types")
