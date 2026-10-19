# Alarms on symptoms, to one email topic (ADR-012, docs/operations/README.md); budget alerts
# warn, they do not stop spending (PRD section 6).

resource "aws_sns_topic" "alarms" {
  name              = "${var.name}-alarms"
  kms_master_key_id = aws_kms_key.main.arn
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.name}-api-5xx"
  alarm_description   = "Runbook RB-02: API 5xx"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = aws_apigatewayv2_api.main.id }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "function_errors" {
  for_each            = local.functions
  alarm_name          = "${var.name}-${each.key}-errors"
  alarm_description   = "Function errors in ${each.key}"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.fn[each.key].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "function_throttles" {
  for_each            = local.functions
  alarm_name          = "${var.name}-${each.key}-throttles"
  alarm_description   = "Runbook RB-03: Lambda concurrency or account quota exhausted"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = aws_lambda_function.fn[each.key].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_log_metric_filter" "mcp_denied" {
  name           = "${var.name}-mcp-denied"
  log_group_name = aws_cloudwatch_log_group.function["mcp-gateway"].name
  pattern        = "{ $.event = \"tool_call\" && $.outcome = \"denied\" }"

  metric_transformation {
    name      = "DeniedToolCalls"
    namespace = "SecondChance/MCP"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "mcp_denied_spike" {
  alarm_name          = "${var.name}-mcp-denied-spike"
  alarm_description   = "MCP policy or rate-limit denials exceed the expected baseline"
  namespace           = "SecondChance/MCP"
  metric_name         = "DeniedToolCalls"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 20
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${var.name}-api-p95-latency"
  alarm_description   = "Runbook RB-03: API p95 latency above 2.5 seconds"
  namespace           = "AWS/ApiGateway"
  metric_name         = "Latency"
  dimensions          = { ApiId = aws_apigatewayv2_api.main.id }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 2500
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "dlq" {
  for_each            = aws_sqs_queue.dlq
  alarm_name          = "${each.value.name}-not-empty"
  alarm_description   = "Runbook RB-01: messages in a dead-letter queue"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "queue_age" {
  for_each            = aws_sqs_queue.main
  alarm_name          = "${each.value.name}-oldest-message"
  alarm_description   = "Work waiting more than 10 minutes (FR-026: mission emails within a minute)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = each.value.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 600
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  # Account-wide on purpose: Bedrock tokens and data transfer carry no resource tags, and a
  # TagKeyValue filter stays at zero until the tag is activated in Billing. Use a dedicated account.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alarm_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alarm_email]
  }
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${var.name}-operations"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title = "API traffic, errors and latency", region = var.region, view = "timeSeries"
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.main.id, { stat = "Sum" }],
            [".", "5xx", ".", ".", { stat = "Sum" }],
            [".", "Latency", ".", ".", { stat = "p95", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title = "Lambda errors and throttles", region = var.region, view = "timeSeries"
          metrics = flatten([
            for key, fn in aws_lambda_function.fn : [
              ["AWS/Lambda", "Errors", "FunctionName", fn.function_name, { label = "${key} errors", stat = "Sum" }],
              [".", "Throttles", ".", ".", { label = "${key} throttles", stat = "Sum" }],
            ]
          ])
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title = "Queue backlog and age", region = var.region, view = "timeSeries"
          metrics = flatten([
            for key, queue in aws_sqs_queue.main : [
              ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", queue.name, { label = "${key} depth", stat = "Maximum" }],
              [".", "ApproximateAgeOfOldestMessage", ".", ".", { label = "${key} age", stat = "Maximum", yAxis = "right" }],
            ]
          ])
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title = "Aurora capacity and connections", region = var.region, view = "timeSeries"
          metrics = [
            ["AWS/RDS", "ServerlessDatabaseCapacity", "DBClusterIdentifier", aws_rds_cluster.main.cluster_identifier, { stat = "Average" }],
            [".", "DatabaseConnections", ".", ".", { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
    ]
  })
}
