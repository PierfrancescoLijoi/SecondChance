# Alarms on symptoms, to one email action group (ADR-012, docs/operations/README.md); the budget warns, it
# does not stop spending (PRD section 6). Container logs are the application's JSON lines (already
# redacted) in Log Analytics; traces and metrics go to Application Insights through the OpenTelemetry
# exporter the application already has.

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${var.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${var.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  retention_in_days   = var.log_retention_days

  # Telemetry is accepted from Entra identities only (Monitoring Metrics Publisher, identity.tf): the
  # connection string in the containers' environment identifies the component and authorises nothing.
  local_authentication_enabled = false
  tags                         = local.tags
}

resource "azurerm_monitor_action_group" "alarms" {
  name                = "ag-${var.name}"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "secondchance"
  tags                = local.tags

  email_receiver {
    name                    = "operators"
    email_address           = var.alarm_email
    use_common_alert_schema = true
  }
}

# --- metric alarms -------------------------------------------------------------------------------------

locals {
  # Names and aggregations are the REST names Azure Monitor documents for each resource type.
  metric_alarms = {
    "api-5xx" = {
      description = "Runbook RB-02: API 5xx"
      scope       = azurerm_container_app.main["api"].id
      namespace   = "Microsoft.App/containerApps"
      metric      = "Requests"
      aggregation = "Total"
      operator    = "GreaterThan"
      threshold   = 5
      window      = "PT5M"
      frequency   = "PT5M"
      dimensions  = [{ name = "statusCodeCategory", values = ["5xx"] }]
    }
    "edge-5xx" = {
      description = "Runbook RB-02: more than 5% of edge responses are 5xx"
      scope       = azurerm_cdn_frontdoor_profile.main.id
      namespace   = "Microsoft.Cdn/profiles"
      metric      = "Percentage5XX"
      aggregation = "Average"
      operator    = "GreaterThan"
      threshold   = 5
      window      = "PT15M"
      frequency   = "PT5M"
      dimensions  = []
    }
    "dead-letters" = {
      description = "Runbook RB-01: messages in a dead-letter queue"
      scope       = azurerm_servicebus_namespace.main.id
      namespace   = "Microsoft.ServiceBus/namespaces"
      metric      = "DeadletteredMessages"
      aggregation = "Maximum"
      operator    = "GreaterThan"
      threshold   = 0
      window      = "PT5M"
      frequency   = "PT5M"
      dimensions  = [{ name = "EntityName", values = ["*"] }]
    }
    "queue-backlog" = {
      description = "Work waiting for more than 15 minutes (FR-026: mission emails within a minute); Service Bus has no age metric, so a standing backlog stands in"
      scope       = azurerm_servicebus_namespace.main.id
      namespace   = "Microsoft.ServiceBus/namespaces"
      metric      = "ActiveMessages"
      aggregation = "Minimum"
      operator    = "GreaterThan"
      threshold   = 20
      window      = "PT15M"
      frequency   = "PT5M"
      dimensions  = [{ name = "EntityName", values = ["*"] }]
    }
    "database-cpu" = {
      description = "Runbook RB-03: database CPU above 85% for 15 minutes"
      scope       = azurerm_postgresql_flexible_server.main.id
      namespace   = "Microsoft.DBforPostgreSQL/flexibleServers"
      metric      = "cpu_percent"
      aggregation = "Average"
      operator    = "GreaterThan"
      threshold   = 85
      window      = "PT15M"
      frequency   = "PT5M"
      dimensions  = []
    }
    "database-storage" = {
      description = "Database storage above 85%"
      scope       = azurerm_postgresql_flexible_server.main.id
      namespace   = "Microsoft.DBforPostgreSQL/flexibleServers"
      metric      = "storage_percent"
      aggregation = "Maximum"
      operator    = "GreaterThan"
      threshold   = 85
      window      = "PT15M"
      frequency   = "PT5M"
      dimensions  = []
    }
    "database-connections" = {
      description = "Runbook RB-03: connections above 80% of the ceiling the replica limits were sized for"
      scope       = azurerm_postgresql_flexible_server.main.id
      namespace   = "Microsoft.DBforPostgreSQL/flexibleServers"
      metric      = "active_connections"
      aggregation = "Maximum"
      operator    = "GreaterThan"
      threshold   = floor(local.postgres_connection_ceiling * 0.8)
      window      = "PT5M"
      frequency   = "PT5M"
      dimensions  = []
    }
    "database-down" = {
      description = "The database does not answer"
      scope       = azurerm_postgresql_flexible_server.main.id
      namespace   = "Microsoft.DBforPostgreSQL/flexibleServers"
      metric      = "is_db_alive"
      aggregation = "Minimum"
      operator    = "LessThan"
      threshold   = 1
      window      = "PT5M"
      frequency   = "PT1M"
      dimensions  = []
    }
  }
}

resource "azurerm_monitor_metric_alert" "main" {
  for_each            = local.metric_alarms
  name                = "${var.name}-${each.key}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [each.value.scope]
  description         = each.value.description
  severity            = 2
  frequency           = each.value.frequency
  window_size         = each.value.window
  auto_mitigate       = true
  tags                = local.tags

  criteria {
    metric_namespace = each.value.namespace
    metric_name      = each.value.metric
    aggregation      = each.value.aggregation
    operator         = each.value.operator
    threshold        = each.value.threshold

    dynamic "dimension" {
      for_each = each.value.dimensions
      content {
        name     = dimension.value.name
        operator = "Include"
        values   = dimension.value.values
      }
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.alarms.id
  }
}

# Restarts of any container: a crash loop that scale-to-zero would otherwise hide.
resource "azurerm_monitor_metric_alert" "restarts" {
  for_each            = azurerm_container_app.main
  name                = "${var.name}-${each.key}-restarts"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [each.value.id]
  description         = "Replicas of ${each.key} keep restarting"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  auto_mitigate       = true
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "RestartCount"
    aggregation      = "Maximum"
    operator         = "GreaterThan"
    threshold        = 3
  }

  action {
    action_group_id = azurerm_monitor_action_group.alarms.id
  }
}

# --- log alarms ----------------------------------------------------------------------------------------

locals {
  log_alarms = {
    "errors" = {
      description = "ERROR lines in the application logs"
      query       = <<-KQL
        ContainerAppConsoleLogs_CL
        | where Log_s has '"level": "ERROR"'
        | summarize errors = count() by ContainerAppName_s
      KQL
      threshold   = 5
      window      = "PT10M"
    }
    "mcp-denied-spike" = {
      description = "MCP policy or rate-limit denials exceed the expected baseline"
      query       = <<-KQL
        ContainerAppConsoleLogs_CL
        | where ContainerAppName_s endswith "-gateway"
        | where Log_s has '"event": "tool_call"' and Log_s has '"outcome": "denied"'
        | summarize denied = count()
      KQL
      threshold   = 20
      window      = "PT5M"
    }
  }
}

# skip_query_validation: the table appears only after the first log line exists. Malware verdicts raise
# Defender for Cloud alerts (portal, and e-mail through Defender's own notification settings), not a query here.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "main" {
  for_each              = local.log_alarms
  name                  = "${var.name}-${each.key}"
  display_name          = "${var.name} ${each.key}"
  description           = each.value.description
  location              = azurerm_resource_group.main.location
  resource_group_name   = azurerm_resource_group.main.name
  scopes                = [azurerm_log_analytics_workspace.main.id]
  severity              = 2
  evaluation_frequency  = "PT5M"
  window_duration       = each.value.window
  skip_query_validation = true
  tags                  = local.tags

  criteria {
    query                   = each.value.query
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = each.value.threshold

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.alarms.id]
  }
}

# --- budget --------------------------------------------------------------------------------------------

resource "azurerm_consumption_budget_resource_group" "main" {
  name              = "${var.name}-monthly"
  resource_group_id = azurerm_resource_group.main.id
  amount            = var.monthly_budget
  time_grain        = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00'Z'", plantimestamp())
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.alarm_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.alarm_email]
  }

  lifecycle {
    ignore_changes = [time_period] # the start date is the first day of the month the budget was created in
  }
}

# --- diagnostics ---------------------------------------------------------------------------------------

resource "azurerm_monitor_diagnostic_setting" "main" {
  for_each = {
    database = { id = azurerm_postgresql_flexible_server.main.id, logs = ["PostgreSQLLogs"] }
    queues   = { id = azurerm_servicebus_namespace.main.id, logs = ["OperationalLogs"] }
    edge     = { id = azurerm_cdn_frontdoor_profile.main.id, logs = ["FrontDoorAccessLog", "FrontDoorWebApplicationFirewallLog"] }
    models   = { id = azurerm_cognitive_account.ai.id, logs = ["Audit", "RequestResponse"] }
    registry = { id = azurerm_container_registry.main.id, logs = ["ContainerRegistryLoginEvents", "ContainerRegistryRepositoryEvents"] }
  }
  name                       = "to-log-analytics"
  target_resource_id         = each.value.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  dynamic "enabled_log" {
    for_each = each.value.logs
    content {
      category = enabled_log.value
    }
  }
}
