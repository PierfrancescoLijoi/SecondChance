# Who may do what (ADR-017 keeps application roles in the database; this file is only the platform side).
# Every workload runs as a user-assigned managed identity with the narrowest roles at the narrowest scope.
# They replace the ten IAM roles of the AWS module, and their names say what they are for:
#
#   acrpull      pulls images (attached to every app and job, used for nothing else)
#   app          the application database role secondchance_app, the queues, the documents, the models, real time
#   agent        asks for gateway tokens: attached to the agent worker only, so the API cannot call tools
#   gateway      the MCP gateway: its rate-limit table, and a token for the tool executor
#   notifier     reads the notify queue, looks addresses up in Graph, sends with ACS
#   maintenance  the database role secondchance_maintenance and the queues it re-feeds
#   migrator     the database role secondchance_migrator (owns the schema)
#   dbadmin      administrator of the server, used by the bootstrap job only
#   scaler       lets KEDA read queue depth; holds the one broad data role (Service Bus Data Owner) on the queues

locals {
  identities = toset(["acrpull", "app", "agent", "gateway", "notifier", "maintenance", "migrator", "dbadmin", "scaler"])
}

resource "azurerm_user_assigned_identity" "main" {
  for_each            = local.identities
  name                = "id-${var.name}-${each.key}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

# --- Azure RBAC ------------------------------------------------------------------------------

locals {
  # Built-in role definitions by id (https://learn.microsoft.com/azure/role-based-access-control/built-in-roles):
  # no name lookup against the subscription, and the Communication role, which the documentation page does not
  # list yet, is addressed the way Azure Verified Modules address it.
  builtin_roles = {
    "AcrPull"                               = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
    "Azure Service Bus Data Sender"         = "69a216fc-b8fb-44d8-bc22-1f3c2cd27a39"
    "Azure Service Bus Data Receiver"       = "4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0"
    "Azure Service Bus Data Owner"          = "090c5cfd-751d-490a-894a-3ce6f1109419"
    "Storage Table Data Contributor"        = "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3"
    "Cognitive Services OpenAI User"        = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
    "Cognitive Services User"               = "a97b65f3-24c7-4388-baec-2e87135dc908"
    "Web PubSub Service Owner"              = "12cf5a90-567b-43ae-8102-96cf46c7d9b4"
    "Monitoring Metrics Publisher"          = "3913510d-42f4-4e42-8a64-420c390055eb"
    "Communication and Email Service Owner" = "09976791-48a7-449e-bb21-39d1a415f350"
  }
  builtin_role_id = { for name, guid in local.builtin_roles : name => "/subscriptions/${local.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${guid}" }
}

resource "azurerm_role_assignment" "acr_pull" {
  scope              = azurerm_container_registry.main.id
  role_definition_id = local.builtin_role_id["AcrPull"]
  principal_id       = azurerm_user_assigned_identity.main["acrpull"].principal_id
  principal_type     = "ServicePrincipal"
}

locals {
  servicebus_grants = {
    for grant in flatten([
      for identity, spec in {
        app         = { queues = ["jobs", "notify", "agents"], roles = ["Azure Service Bus Data Sender", "Azure Service Bus Data Receiver"] }
        maintenance = { queues = ["jobs", "notify", "agents"], roles = ["Azure Service Bus Data Sender"] }
        notifier    = { queues = ["notify"], roles = ["Azure Service Bus Data Receiver"] }
        } : [
        for queue in spec.queues : [
          for role in spec.roles : { key = "${identity}/${queue}/${role}", identity = identity, queue = queue, role = role }
        ]
      ]
    ]) : grant.key => grant
  }
}

resource "azurerm_role_assignment" "servicebus" {
  for_each           = local.servicebus_grants
  scope              = azurerm_servicebus_queue.main[each.value.queue].id
  role_definition_id = local.builtin_role_id[each.value.role]
  principal_id       = azurerm_user_assigned_identity.main[each.value.identity].principal_id
  principal_type     = "ServicePrincipal"
}

# KEDA's Service Bus scaler reads the queue's runtime properties, a management-plane read that the
# Receiver role does not cover. The scaler identity holds Data Owner on the three queues and nothing else.
resource "azurerm_role_assignment" "scaler" {
  for_each           = azurerm_servicebus_queue.main
  scope              = each.value.id
  role_definition_id = local.builtin_role_id["Azure Service Bus Data Owner"]
  principal_id       = azurerm_user_assigned_identity.main["scaler"].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "objects" {
  scope              = azurerm_storage_container.objects.id
  role_definition_id = azurerm_role_definition.objects.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.main["app"].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "table" {
  scope              = azurerm_storage_table.rate_limit.id
  role_definition_id = local.builtin_role_id["Storage Table Data Contributor"]
  principal_id       = azurerm_user_assigned_identity.main["gateway"].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "ai" {
  for_each           = toset(["Cognitive Services OpenAI User", "Cognitive Services User"])
  scope              = azurerm_cognitive_account.ai.id
  role_definition_id = local.builtin_role_id[each.value]
  principal_id       = azurerm_user_assigned_identity.main["app"].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "pubsub" {
  scope              = azurerm_web_pubsub.main.id
  role_definition_id = local.builtin_role_id["Web PubSub Service Owner"]
  principal_id       = azurerm_user_assigned_identity.main["app"].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "telemetry" {
  for_each           = toset(["app", "notifier"])
  scope              = azurerm_application_insights.main.id
  role_definition_id = local.builtin_role_id["Monitoring Metrics Publisher"]
  principal_id       = azurerm_user_assigned_identity.main[each.key].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "email" {
  scope              = azurerm_communication_service.main.id
  role_definition_id = local.builtin_role_id["Communication and Email Service Owner"]
  principal_id       = azurerm_user_assigned_identity.main["notifier"].principal_id
  principal_type     = "ServicePrincipal"
}

# --- Entra: the sign-in app registration (web app and API in one) -------------------------------------

resource "azuread_application" "web" {
  count            = var.create_app_registrations ? 1 : 0
  display_name     = "${var.name}-web"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  api {
    requested_access_token_version = 2 # v2.0 tokens: the API validates iss, aud, scp and oid (secondchance.auth)

    oauth2_permission_scope {
      id                         = uuidv5("url", "https://secondchance.invalid/scopes/${var.name}/access_as_user")
      value                      = "access_as_user"
      type                       = "User"
      enabled                    = true
      admin_consent_display_name = "Use SecondChance"
      admin_consent_description  = "Use SecondChance on behalf of the signed-in user"
      user_consent_display_name  = "Use SecondChance"
      user_consent_description   = "Use SecondChance on your behalf"
    }
  }

  # Authorization code + PKCE from the browser: no client secret exists (ADR-018).
  single_page_application {
    redirect_uris = ["${local.web_origin}/callback", "${local.web_origin}/"]
  }

  optional_claims {
    access_token {
      name = "email"
    }
  }

  lifecycle {
    ignore_changes = [identifier_uris] # owned by azuread_application_identifier_uri below
  }
}

resource "azuread_application_identifier_uri" "web" {
  count          = var.create_app_registrations ? 1 : 0
  application_id = azuread_application.web[0].id
  identifier_uri = "api://${azuread_application.web[0].client_id}"
}

resource "azuread_service_principal" "web" {
  count                        = var.create_app_registrations ? 1 : 0
  client_id                    = azuread_application.web[0].client_id
  app_role_assignment_required = false
  owners                       = [data.azuread_client_config.current.object_id]
}

# --- Entra: service-to-service authentication (replaces Lambda invoke permissions) --------------------

locals {
  service_apps = var.create_app_registrations ? {
    gateway  = { role = "Tool.Invoke", description = "Call the MCP tool gateway", caller = "agent" }
    executor = { role = "Tool.Execute", description = "Call the private tool executor", caller = "gateway" }
  } : {}
}

resource "azuread_application" "service" {
  for_each         = local.service_apps
  display_name     = "${var.name}-${each.key}"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  api {
    requested_access_token_version = 2
  }

  app_role {
    allowed_member_types = ["Application"]
    id                   = uuidv5("url", "https://secondchance.invalid/roles/${var.name}/${each.value.role}")
    value                = each.value.role
    display_name         = each.value.role
    description          = each.value.description
    enabled              = true
  }

  lifecycle {
    ignore_changes = [identifier_uris]
  }
}

resource "azuread_application_identifier_uri" "service" {
  for_each       = local.service_apps
  application_id = azuread_application.service[each.key].id
  identifier_uri = "api://${azuread_application.service[each.key].client_id}"
}

resource "azuread_service_principal" "service" {
  for_each                     = local.service_apps
  client_id                    = azuread_application.service[each.key].client_id
  app_role_assignment_required = true # a token is issued only to identities holding the role below
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_app_role_assignment" "service" {
  for_each            = local.service_apps
  app_role_id         = uuidv5("url", "https://secondchance.invalid/roles/${var.name}/${each.value.role}")
  principal_object_id = azurerm_user_assigned_identity.main[each.value.caller].principal_id
  resource_object_id  = azuread_service_principal.service[each.key].object_id
}

# The notifier finds a recipient's address by object id. Graph offers no narrower application permission
# for reading one user's mail attribute, so this is the one broad Entra grant of the deployment (documented
# as a residual risk in docs/security/threat-model.md); the code puts only a validated GUID in the URL.
data "azuread_application_published_app_ids" "well_known" {}

resource "azuread_service_principal" "msgraph" {
  count        = var.create_app_registrations ? 1 : 0
  client_id    = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  use_existing = true
}

resource "azuread_app_role_assignment" "notifier_graph" {
  count               = var.create_app_registrations ? 1 : 0
  app_role_id         = azuread_service_principal.msgraph[0].app_role_ids["User.Read.All"]
  principal_object_id = azurerm_user_assigned_identity.main["notifier"].principal_id
  resource_object_id  = azuread_service_principal.msgraph[0].object_id
}

locals {
  gateway_client_id  = var.create_app_registrations ? azuread_application.service["gateway"].client_id : ""
  executor_client_id = var.create_app_registrations ? azuread_application.service["executor"].client_id : ""
}
