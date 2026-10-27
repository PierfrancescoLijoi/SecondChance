# Offline evaluation of the whole module with mocked providers: no Azure account, no network. It proves the
# configuration plans, that the cross-references resolve, and the guarantees the design promises (nothing
# holds a secret, every data store is private, the replica limits fit the database, the apps get the
# environment the application code reads). What it cannot prove -- quotas, names already taken, model
# availability in the region, Entra permissions -- is what scripts/azure/connect.sh checks against the real
# subscription before the first apply.

mock_provider "azurerm" {
  source = "./tests/mocks/azurerm"
}

mock_provider "azuread" {
  mock_data "azuread_client_config" {
    defaults = {
      tenant_id = "11111111-2222-3333-4444-555555555555"
      object_id = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
      client_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }
  }
  mock_data "azuread_application_published_app_ids" {
    defaults = {
      result = { MicrosoftGraph = "00000003-0000-0000-c000-000000000000" }
    }
  }
  mock_resource "azuread_service_principal" {
    defaults = {
      object_id    = "cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee"
      app_role_ids = { "User.Read.All" = "df021288-bdef-4463-88db-98f22de89214" }
    }
  }
  mock_resource "azuread_application" {
    defaults = {
      client_id = "dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee"
      id        = "/applications/dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee"
    }
  }
}

mock_provider "time" {}

variables {
  name        = "secondchance-demo"
  environment = "demo"
  image_tag   = "abc123"
  alarm_email = "ops@example.org"
}

run "demo_plans_with_every_service_private_and_keyless" {
  command = apply

  assert {
    condition     = azurerm_storage_account.objects.shared_access_key_enabled == false && azurerm_storage_account.objects.allow_nested_items_to_be_public == false
    error_message = "The document store must not accept shared keys or public blobs."
  }
  assert {
    condition     = azurerm_servicebus_namespace.main.local_auth_enabled == false && azurerm_cognitive_account.ai.local_auth_enabled == false && azurerm_web_pubsub.main.local_auth_enabled == false
    error_message = "Service Bus, the AI account and Web PubSub must accept Entra tokens only."
  }
  assert {
    condition     = azurerm_postgresql_flexible_server.main.public_network_access_enabled == false && one(azurerm_postgresql_flexible_server.main.authentication).password_auth_enabled == false
    error_message = "PostgreSQL must be private and passwordless."
  }
  assert {
    condition     = azurerm_container_registry.main.admin_enabled == false && azurerm_container_registry.main.anonymous_pull_enabled == false
    error_message = "The registry must not have an admin user or anonymous pulls."
  }
  assert {
    condition     = azurerm_cognitive_account.ai.public_network_access_enabled == false
    error_message = "The models are reached through the private endpoint only."
  }
}

run "container_apps_get_the_environment_the_code_reads" {
  command = apply

  assert {
    condition     = toset(keys(azurerm_container_app.main)) == toset(["web", "api", "jobs", "agents", "notifier", "gateway", "executor"])
    error_message = "One Container App per role of the AWS function families."
  }
  assert {
    condition     = azurerm_container_app.main["api"].ingress[0].external_enabled && azurerm_container_app.main["web"].ingress[0].external_enabled && !azurerm_container_app.main["gateway"].ingress[0].external_enabled && !azurerm_container_app.main["executor"].ingress[0].external_enabled
    error_message = "Only the API and the web container are reachable from Front Door; the tool path is internal."
  }
  assert {
    condition     = length(azurerm_container_app.main["jobs"].ingress) == 0 && length(azurerm_container_app.main["agents"].ingress) == 0 && length(azurerm_container_app.main["notifier"].ingress) == 0
    error_message = "Queue consumers expose nothing."
  }
  assert {
    condition = alltrue([
      for name in ["SECONDCHANCE_CLOUD", "SECONDCHANCE_AUTH_MODE", "SECONDCHANCE_DB_ENTRA_AUTH", "SECONDCHANCE_DATABASE_URL", "SECONDCHANCE_BLOB_ENDPOINT", "SECONDCHANCE_SERVICEBUS_NAMESPACE", "SECONDCHANCE_WEBPUBSUB_ENDPOINT", "SECONDCHANCE_AZURE_OPENAI_ENDPOINT", "SECONDCHANCE_CONTENT_SAFETY_ENDPOINT", "SECONDCHANCE_FRONT_DOOR_ID"]
      : contains([for e in azurerm_container_app.main["api"].template[0].container[0].env : e.name], name)
    ])
    error_message = "The API must receive every setting the Azure adapters read."
  }
  assert {
    condition     = [for e in azurerm_container_app.main["api"].template[0].container[0].env : e.value if e.name == "SECONDCHANCE_AUTH_MODE"] == ["entra"]
    error_message = "The application must verify Entra tokens."
  }
  assert {
    condition = alltrue(flatten([
      for app in azurerm_container_app.main : [
        for e in app.template[0].container[0].env :
        (e.name == "APPLICATIONINSIGHTS_CONNECTION_STRING" || !can(regex("(?i)(password|secret|accountkey|sharedaccess|connection_string$)", e.name))) && !can(regex("://[^@/ ]+:[^@/ ]+@", e.value))
      ]
    ]))
    error_message = "No secret-shaped variable and no password-bearing URL may reach a container."
  }
  assert {
    condition     = alltrue(flatten([for app in azurerm_container_app.main : [for e in app.template[0].container[0].env : e.name != "SECONDCHANCE_MCP_GATEWAY_URL"] if app != azurerm_container_app.main["agents"]]))
    error_message = "Only the agent worker is wired to the gateway."
  }
  assert {
    condition     = [for app, identities in output.app_identities : app if contains(identities, "agent")] == ["agents"] && [for app, identities in output.app_identities : app if contains(identities, "dbadmin")] == []
    error_message = "Only the agent worker may hold the identity that can obtain gateway tokens."
  }
  assert {
    condition     = alltrue([for app in azurerm_container_app.main : length(app.registry) == 1 && app.registry[0].server == azurerm_container_registry.main.login_server])
    error_message = "Every app pulls from the environment's registry with an identity, never a password."
  }
}

run "queues_dead_letter_after_five_deliveries" {
  command = apply

  assert {
    condition     = alltrue([for queue in azurerm_servicebus_queue.main : queue.max_delivery_count == 5 && queue.dead_lettering_on_message_expiration])
    error_message = "ADR-005: five attempts, then the dead-letter queue."
  }
  assert {
    condition     = toset(keys(azurerm_servicebus_queue.main)) == toset(["jobs", "notify", "agents"])
    error_message = "The queues of the AWS stack plus the agents queue that replaces Step Functions."
  }
}

run "demo_connection_budget_fits_the_smallest_database" {
  command = apply

  assert {
    condition     = output.database_connection_budget.peak <= floor(output.database_connection_budget.ceiling * 0.8)
    error_message = "ADR-006: replicas x pool must fit the database."
  }
}

run "demo_has_the_seed_and_smoke_jobs_and_the_pilot_does_not" {
  command = apply

  assert {
    condition     = contains(keys(azurerm_container_app_job.main), "seed") && contains(keys(azurerm_container_app_job.main), "tools")
    error_message = "The demo seeds synthetic knowledge and smoke-tests the gateway."
  }
}

run "pilot_is_zone_redundant_protected_and_on_the_premium_edge" {
  command = apply

  variables {
    name                       = "secondchance-pilot"
    environment                = "pilot"
    front_door_sku             = "Premium_AzureFrontDoor"
    postgres_sku_name          = "GP_Standard_D2ds_v5"
    postgres_high_availability = true
    servicebus_sku             = "Premium"
    web_pubsub_sku             = "Standard_S1"
    storage_replication        = "ZRS"
    deletion_protection        = true
    zone_redundant             = true
    nat_gateway                = true
    geo_redundant_backup       = true
    backup_retention_days      = 14
    requeue_cron               = "*/2 * * * *"
    api_min_replicas           = 1
    gateway_min_replicas       = 1
    worker_min_replicas        = 1
    max_replicas               = { api = 10, jobs = 5, agents = 5, notifier = 2, gateway = 5, executor = 5, web = 3 }
    db_pool_size               = 5
    db_max_overflow            = 3
  }

  assert {
    condition     = length(azurerm_management_lock.database) == 1 && length(azurerm_management_lock.objects) == 1
    error_message = "Deletion protection must lock the database and the document store."
  }
  assert {
    condition     = contains(keys(azurerm_private_endpoint.main), "servicebus") && length(azurerm_nat_gateway.main) == 1
    error_message = "The pilot reaches Service Bus privately and leaves through one known address."
  }
  assert {
    condition     = length(azurerm_cdn_frontdoor_firewall_policy.main.managed_rule) == 2
    error_message = "The Premium edge carries the default and bot rule sets."
  }
  assert {
    condition     = !contains(keys(azurerm_container_app_job.main), "seed") && !contains(keys(azurerm_container_app_job.main), "tools")
    error_message = "Synthetic data never reaches the pilot."
  }
}

run "global_model_deployments_are_refused_for_eu_residency" {
  command = plan

  variables {
    chat_model = { name = "gpt-4.1-mini", version = "2025-04-14", sku = "GlobalStandard", capacity = 10 }
  }

  expect_failures = [var.chat_model]
}

run "too_many_replicas_for_the_database_fail_at_plan_time" {
  command = plan

  variables {
    max_replicas = { api = 20, jobs = 20, agents = 20, notifier = 1, gateway = 2, executor = 20, web = 2 }
  }

  expect_failures = [azurerm_postgresql_flexible_server.main]
}

run "regions_outside_the_eu_are_refused" {
  command = plan

  variables {
    location = "eastus"
  }

  expect_failures = [var.location]
}

run "without_entra_write_access_the_app_registration_is_bring_your_own" {
  command = apply

  variables {
    create_app_registrations = false
    oidc_client_id           = "12345678-1234-1234-1234-123456789012"
  }

  assert {
    condition     = output.oidc_client_id == "12345678-1234-1234-1234-123456789012" && length(azuread_application.web) == 0
    error_message = "A supplied registration is used and nothing is created in Entra."
  }
  assert {
    condition     = !contains([for e in azurerm_container_app.main["gateway"].template[0].container[0].env : e.name], "SECONDCHANCE_SERVICE_AUTH_AUDIENCE")
    error_message = "Without app registrations, service tokens are not required (the network is the boundary)."
  }
}
