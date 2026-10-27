# Containers instead of functions (ADR-001 on Azure, ADR-023). One registry, three images (app, gateway, web),
# and one Container Apps environment in the virtual network. Apps scale to zero between requests or
# messages (KEDA reads the Service Bus queues with the scaler identity); the replica ceilings are the
# bulkhead that Lambda reserved concurrency was, checked against the database in data.tf.

resource "azurerm_container_registry" "main" {
  name                          = "${local.compact}${local.suffix}"
  location                      = azurerm_resource_group.main.location
  resource_group_name           = azurerm_resource_group.main.name
  sku                           = var.acr_sku
  admin_enabled                 = false # pulls use the acrpull identity
  anonymous_pull_enabled        = false
  public_network_access_enabled = true # CI pushes from outside the network; every pull and push needs an Entra token
  tags                          = local.tags
}

resource "azurerm_container_app_environment" "main" {
  name                               = "cae-${var.name}"
  location                           = azurerm_resource_group.main.location
  resource_group_name                = azurerm_resource_group.main.name
  log_analytics_workspace_id         = azurerm_log_analytics_workspace.main.id
  logs_destination                   = "log-analytics"
  infrastructure_subnet_id           = azurerm_subnet.aca.id
  infrastructure_resource_group_name = "rg-${var.name}-aca"
  internal_load_balancer_enabled     = false
  public_network_access              = "Enabled"
  zone_redundancy_enabled            = var.zone_redundant
  tags                               = local.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  depends_on = [azurerm_subnet_nat_gateway_association.aca]
}

locals {
  env_domain = azurerm_container_app_environment.main.default_domain
  images = {
    app     = "${azurerm_container_registry.main.login_server}/app:${var.image_tag}"
    gateway = "${azurerm_container_registry.main.login_server}/gateway:${var.image_tag}"
    web     = "${azurerm_container_registry.main.login_server}/web:${var.image_tag}"
  }

  # Apps in one environment reach each other on internal ingress; the name is fixed, so no resource has to
  # refer to another one of the same family (which Terraform would call a cycle).
  gateway_url  = "https://${var.name}-gateway.internal.${local.env_domain}"
  executor_url = "https://${var.name}-executor.internal.${local.env_domain}"

  # What every container knows: where the cloud services are, never a secret.
  base_env = {
    SECONDCHANCE_CLOUD                    = "azure"
    SECONDCHANCE_ENV                      = var.environment
    SECONDCHANCE_LOG_LEVEL                = "INFO"
    SECONDCHANCE_SERVICEBUS_NAMESPACE     = "${azurerm_servicebus_namespace.main.name}.servicebus.windows.net"
    SECONDCHANCE_QUEUE_JOBS               = azurerm_servicebus_queue.main["jobs"].name
    SECONDCHANCE_QUEUE_NOTIFY             = azurerm_servicebus_queue.main["notify"].name
    SECONDCHANCE_QUEUE_AGENTS             = azurerm_servicebus_queue.main["agents"].name
    OTEL_SERVICE_NAME                     = "secondchance-${var.environment}"
    OTEL_RESOURCE_ATTRIBUTES              = "deployment.environment=${var.environment},service.namespace=secondchance"
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.main.connection_string
  }

  # What the application containers need on top: identity, database, objects, models, real time.
  common_env = merge(local.base_env, {
    SECONDCHANCE_AUTH_MODE                         = "entra"
    SECONDCHANCE_ENTRA_ISSUER                      = local.oidc_issuer
    SECONDCHANCE_ENTRA_AUDIENCE                    = "${local.oidc_client_id},api://${local.oidc_client_id}"
    SECONDCHANCE_ENTRA_JWKS_URI                    = local.oidc_jwks_uri
    SECONDCHANCE_ENTRA_TENANT_ID                   = local.tenant_id
    SECONDCHANCE_ENTRA_AUTHORITY_HOST              = var.entra_authority_host
    SECONDCHANCE_DB_ENTRA_AUTH                     = "1"
    SECONDCHANCE_DATABASE_URL                      = local.db_url["secondchance_app"]
    SECONDCHANCE_DB_POOL_SIZE                      = tostring(var.db_pool_size)
    SECONDCHANCE_DB_MAX_OVERFLOW                   = tostring(var.db_max_overflow)
    SECONDCHANCE_BLOB_ENDPOINT                     = "https://${azurerm_storage_account.objects.name}.blob.core.windows.net"
    SECONDCHANCE_BLOB_CONTAINER                    = azurerm_storage_container.objects.name
    SECONDCHANCE_WEBPUBSUB_ENDPOINT                = local.web_pubsub_endpoint
    SECONDCHANCE_WEBPUBSUB_HUB                     = azurerm_web_pubsub_hub.runs.name
    SECONDCHANCE_EMBEDDINGS                        = "azure_openai"
    SECONDCHANCE_AZURE_OPENAI_ENDPOINT             = local.openai_endpoint
    SECONDCHANCE_AZURE_OPENAI_EMBEDDING_DEPLOYMENT = azurerm_cognitive_deployment.embedding.name
    SECONDCHANCE_LLM                               = var.llm_mode
    SECONDCHANCE_CONTENT_SAFETY_ENDPOINT           = local.content_safety_endpoint
    SECONDCHANCE_GROUNDEDNESS                      = var.content_safety_groundedness ? "1" : "0"
    SECONDCHANCE_ROUTER_MODE                       = var.router_mode
    SECONDCHANCE_LIMIT_UPLOAD_BYTES                = tostring(var.upload_limit_bytes)
    SECONDCHANCE_WEB_ORIGINS                       = local.web_origin
    SECONDCHANCE_WEB_URL                           = local.web_origin
    }, var.llm_mode == "azure_openai" ? {
    SECONDCHANCE_AZURE_OPENAI_CHAT_DEPLOYMENT = azurerm_cognitive_deployment.chat[0].name
  } : {})

  service_auth_env = var.create_app_registrations ? {
    SECONDCHANCE_ENTRA_TENANT_ID        = local.tenant_id
    SECONDCHANCE_ENTRA_AUTHORITY_HOST   = var.entra_authority_host
    SECONDCHANCE_MCP_GATEWAY_AUDIENCE   = local.gateway_client_id
    SECONDCHANCE_TOOL_EXECUTOR_AUDIENCE = local.executor_client_id
  } : {}

  # kind: service (ingress) or worker (queue consumer). identities[0] is the one AZURE_CLIENT_ID selects.
  apps = {
    web = {
      image      = local.images.web
      command    = null
      cpu        = 0.25
      memory     = "0.5Gi"
      identities = []
      ingress    = { external = true, port = 8080 }
      scale      = { http = 50 }
      min        = var.web_min_replicas
      max        = var.max_replicas.web
      env = {
        FRONT_DOOR_ID   = azurerm_cdn_frontdoor_profile.main.resource_guid
        CSP_CONNECT_SRC = "https://${var.entra_authority_host} wss://${azurerm_web_pubsub.main.hostname}"
        CSP_FORM_ACTION = "https://${var.entra_authority_host}"
        WEB_CONFIG_JSON = local.web_config
      }
      use_common_env = false
      base           = false
    }
    api = {
      image          = local.images.app
      command        = null # the image's own CMD: uvicorn secondchance.main:app
      cpu            = 0.5
      memory         = "1Gi"
      identities     = ["app"]
      ingress        = { external = true, port = 8000 }
      scale          = { http = 30 }
      min            = var.api_min_replicas
      max            = var.max_replicas.api
      env            = { SECONDCHANCE_FRONT_DOOR_ID = azurerm_cdn_frontdoor_profile.main.resource_guid }
      use_common_env = true
      base           = true
    }
    jobs = {
      image          = local.images.app
      command        = ["python", "-m", "secondchance.jobs"]
      cpu            = 1
      memory         = "2Gi"
      identities     = ["app", "scaler"]
      ingress        = null
      scale          = { queue = "jobs", messages = 1 } # one PDF or solver run per replica
      min            = var.worker_min_replicas
      max            = var.max_replicas.jobs
      env            = var.defender_malware_scanning ? { SECONDCHANCE_MALWARE_SCAN = "defender" } : {}
      use_common_env = true
      base           = true
    }
    agents = {
      image      = local.images.app
      command    = ["python", "-m", "secondchance.agents.worker"]
      cpu        = 0.5
      memory     = "1Gi"
      identities = ["app", "agent", "scaler"]
      ingress    = null
      scale      = { queue = "agents", messages = 2 }
      min        = var.worker_min_replicas
      max        = var.max_replicas.agents
      env = merge(local.service_auth_env, {
        SECONDCHANCE_MCP_GATEWAY_URL            = local.gateway_url
        SECONDCHANCE_SERVICE_IDENTITY_CLIENT_ID = azurerm_user_assigned_identity.main["agent"].client_id
      })
      use_common_env = true
      base           = true
    }
    notifier = {
      image      = local.images.app
      command    = ["python", "-m", "secondchance.notify"]
      cpu        = 0.25
      memory     = "0.5Gi"
      identities = ["notifier", "scaler"]
      ingress    = null
      scale      = { queue = "notify", messages = 10 }
      min        = var.worker_min_replicas
      max        = var.max_replicas.notifier
      env = {
        SECONDCHANCE_NOTIFY_DIRECTORY = "graph"
        SECONDCHANCE_MAILER           = "acs"
        SECONDCHANCE_MAIL_FROM        = local.notification_from
        SECONDCHANCE_ACS_ENDPOINT     = local.acs_endpoint
        SECONDCHANCE_WEB_URL          = local.web_origin
      }
      use_common_env = false
      base           = true
    }
    gateway = {
      image      = local.images.gateway
      command    = null # the image's own CMD: uvicorn mcp_gateway.app:app on 8010
      cpu        = 0.25
      memory     = "0.5Gi"
      identities = ["gateway"]
      ingress    = { external = false, port = 8010 }
      scale      = { http = 50 }
      min        = var.gateway_min_replicas
      max        = var.max_replicas.gateway
      env = merge(local.service_auth_env, var.create_app_registrations ? {
        SECONDCHANCE_SERVICE_AUTH_AUDIENCE = local.gateway_client_id
        } : {}, {
        SECONDCHANCE_TOOL_EXECUTOR_URL             = local.executor_url
        SECONDCHANCE_MCP_RATE_LIMIT_TABLE_ENDPOINT = "https://${azurerm_storage_account.objects.name}.table.core.windows.net"
        SECONDCHANCE_MCP_RATE_LIMIT_TABLE          = azurerm_storage_table.rate_limit.name
      })
      use_common_env = false
      base           = true
    }
    executor = {
      image      = local.images.app
      command    = ["uvicorn", "secondchance.tool_executor_app:app", "--host", "0.0.0.0", "--port", "8020"]
      cpu        = 0.5
      memory     = "1Gi"
      identities = ["app"]
      ingress    = { external = false, port = 8020 }
      scale      = { http = 30 }
      min        = var.gateway_min_replicas
      max        = var.max_replicas.executor
      env = var.create_app_registrations ? {
        SECONDCHANCE_SERVICE_AUTH_AUDIENCE = local.executor_client_id
      } : {}
      use_common_env = true
      base           = true
    }
  }
}

resource "azurerm_container_app" "main" {
  for_each                     = local.apps
  name                         = "${var.name}-${each.key}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type = "UserAssigned"
    identity_ids = concat(
      [azurerm_user_assigned_identity.main["acrpull"].id],
      [for key in each.value.identities : azurerm_user_assigned_identity.main[key].id]
    )
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.main["acrpull"].id
  }

  dynamic "ingress" {
    for_each = each.value.ingress == null ? [] : [each.value.ingress]
    content {
      external_enabled           = ingress.value.external
      target_port                = ingress.value.port
      transport                  = "auto"
      allow_insecure_connections = false

      traffic_weight {
        latest_revision = true
        percentage      = 100
      }
    }
  }

  template {
    min_replicas = each.value.min
    max_replicas = each.value.max

    container {
      name    = each.key
      image   = each.value.image
      command = each.value.command
      cpu     = each.value.cpu
      memory  = each.value.memory

      dynamic "env" {
        for_each = merge(
          each.value.base ? local.base_env : {},
          each.value.use_common_env ? local.common_env : {},
          each.value.env,
          length(each.value.identities) == 0 ? {} : { AZURE_CLIENT_ID = azurerm_user_assigned_identity.main[each.value.identities[0]].client_id },
        )
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "startup_probe" {
        for_each = each.value.ingress == null ? [] : [each.value.ingress]
        content {
          transport               = "HTTP"
          port                    = startup_probe.value.port
          path                    = "/health"
          interval_seconds        = 10
          failure_count_threshold = 10 # 100 seconds: a cold container imports the whole stack
        }
      }

      dynamic "liveness_probe" {
        for_each = each.value.ingress == null ? [] : [each.value.ingress]
        content {
          transport               = "HTTP"
          port                    = liveness_probe.value.port
          path                    = "/health"
          interval_seconds        = 30
          failure_count_threshold = 3
        }
      }
    }

    dynamic "http_scale_rule" {
      for_each = try(each.value.scale.http, null) == null ? [] : [each.value.scale.http]
      content {
        name                = "http"
        concurrent_requests = tostring(http_scale_rule.value)
      }
    }

    dynamic "custom_scale_rule" {
      for_each = try(each.value.scale.queue, null) == null ? [] : [each.value.scale]
      content {
        name             = "queue-${custom_scale_rule.value.queue}"
        custom_rule_type = "azure-servicebus"
        identity_id      = azurerm_user_assigned_identity.main["scaler"].id
        metadata = {
          queueName    = custom_scale_rule.value.queue
          namespace    = azurerm_servicebus_namespace.main.name
          messageCount = tostring(custom_scale_rule.value.messages)
        }
      }
    }
  }

  depends_on = [time_sleep.role_propagation]
}

# --- Jobs: administration and maintenance (EventBridge Scheduler + one-off Lambdas on AWS) -------------------

locals {
  jobs = merge({
    bootstrap = {
      task       = "bootstrap"
      trigger    = "manual"
      identities = ["dbadmin"]
      timeout    = 600
      env = {
        SECONDCHANCE_DB_HOST       = local.db_host
        SECONDCHANCE_DB_ADMIN_USER = azurerm_user_assigned_identity.main["dbadmin"].name
        SECONDCHANCE_DB_PRINCIPALS = jsonencode({
          secondchance_app         = azurerm_user_assigned_identity.main["app"].principal_id
          secondchance_migrator    = azurerm_user_assigned_identity.main["migrator"].principal_id
          secondchance_maintenance = azurerm_user_assigned_identity.main["maintenance"].principal_id
        })
      }
    }
    migrate = {
      task       = "migrate"
      trigger    = "manual"
      identities = ["migrator"]
      timeout    = 900
      env        = { SECONDCHANCE_MIGRATOR_URL = local.db_url["secondchance_migrator"] }
    }
    retention = {
      task       = "retention"
      trigger    = "0 3 * * *" # daily, 03:00 UTC (ADR-014)
      identities = ["maintenance"]
      timeout    = 300
      env        = { SECONDCHANCE_MAINTENANCE_URL = local.db_url["secondchance_maintenance"] }
    }
    requeue = {
      task       = "requeue"
      trigger    = var.requeue_cron # lost messages and expired leases (ADR-010, ADR-015)
      identities = ["maintenance"]
      timeout    = 110
      env        = { SECONDCHANCE_MAINTENANCE_URL = local.db_url["secondchance_maintenance"] }
    }
    ping = {
      task       = "ping"
      trigger    = "manual"
      identities = ["app"]
      timeout    = 120
      env        = {}
    }
    check = {
      task       = "check"
      trigger    = "manual"
      identities = ["app", "agent"]
      timeout    = 300
      env = merge(local.service_auth_env, {
        SECONDCHANCE_MCP_GATEWAY_URL            = local.gateway_url
        SECONDCHANCE_SERVICE_IDENTITY_CLIENT_ID = azurerm_user_assigned_identity.main["agent"].client_id
      })
    }
    }, var.environment == "demo" ? {
    seed = {
      task       = "seed"
      trigger    = "manual"
      identities = ["app"]
      timeout    = 900
      env        = {}
    }
    tools = {
      task       = "tools"
      trigger    = "manual"
      identities = ["app", "agent"]
      timeout    = 120
      env = merge(local.service_auth_env, {
        SECONDCHANCE_MCP_GATEWAY_URL            = local.gateway_url
        SECONDCHANCE_SERVICE_IDENTITY_CLIENT_ID = azurerm_user_assigned_identity.main["agent"].client_id
      })
    }
  } : {})
}

resource "azurerm_container_app_job" "main" {
  for_each                     = local.jobs
  name                         = "${var.name}-${each.key}"
  location                     = azurerm_resource_group.main.location
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = each.value.timeout
  replica_retry_limit          = 0
  tags                         = local.tags

  identity {
    type = "UserAssigned"
    identity_ids = concat(
      [azurerm_user_assigned_identity.main["acrpull"].id],
      [for key in each.value.identities : azurerm_user_assigned_identity.main[key].id]
    )
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.main["acrpull"].id
  }

  dynamic "manual_trigger_config" {
    for_each = each.value.trigger == "manual" ? [1] : []
    content {
      parallelism              = 1
      replica_completion_count = 1
    }
  }

  dynamic "schedule_trigger_config" {
    for_each = each.value.trigger == "manual" ? [] : [each.value.trigger]
    content {
      cron_expression          = schedule_trigger_config.value
      parallelism              = 1
      replica_completion_count = 1
    }
  }

  template {
    container {
      name    = each.key
      image   = local.images.app
      command = ["python", "-m", "secondchance.azure_entry", each.value.task]
      cpu     = each.key == "seed" ? 1 : 0.5
      memory  = each.key == "seed" ? "2Gi" : "1Gi"

      dynamic "env" {
        for_each = merge(
          local.common_env,
          each.value.env,
          { AZURE_CLIENT_ID = azurerm_user_assigned_identity.main[each.value.identities[0]].client_id },
        )
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [time_sleep.role_propagation]
}
