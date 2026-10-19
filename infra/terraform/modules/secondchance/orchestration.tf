# Standard Workflows provide durable, auditable orchestration outside the 15-minute
# Lambda ceiling. Each task invocation remains short and stateless; run state and hard
# budgets remain authoritative in Aurora.

resource "aws_cloudwatch_log_group" "agent_workflow" {
  name              = "/aws/vendedlogs/states/${var.name}-agents"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.main.arn
}

data "aws_iam_policy_document" "step_functions_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "agent_workflow" {
  name               = "${var.name}-agent-workflow"
  assume_role_policy = data.aws_iam_policy_document.step_functions_trust.json
}

resource "aws_iam_role_policy" "agent_workflow" {
  role = aws_iam_role.agent_workflow.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = [aws_lambda_function.fn["agent-step"].arn, format("%s:*", aws_lambda_function.fn["agent-step"].arn)]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_sfn_state_machine" "agents" {
  name     = "${var.name}-agents"
  role_arn = aws_iam_role.agent_workflow.arn
  type     = "STANDARD"

  definition = jsonencode({
    Comment = "Durable, budgeted SecondChance multi-agent execution"
    StartAt = "Execute bounded agent step"
    States = {
      "Execute bounded agent step" = {
        Type     = "Task"
        Resource = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.fn["agent-step"].arn
          "Payload.$"  = "$"
        }
        OutputPath = "$.Payload"
        Retry = [{
          ErrorEquals     = ["States.ALL"]
          IntervalSeconds = 2
          BackoffRate     = 2
          MaxAttempts     = 6
        }]
        Next = "Retry after lease?"
      }
      "Retry after lease?" = {
        Type    = "Choice"
        Choices = [{ Variable = "$.retry", BooleanEquals = true, Next = "Wait for lease" }]
        Default = "Continue?"
      }
      "Wait for lease" = {
        Type    = "Wait"
        Seconds = 30
        Next    = "Execute bounded agent step"
      }
      "Continue?" = {
        Type    = "Choice"
        Choices = [{ Variable = "$.continue", BooleanEquals = true, Next = "Execute bounded agent step" }]
        Default = "Run complete"
      }
      "Run complete" = { Type = "Succeed" }
    }
  })

  logging_configuration {
    include_execution_data = false
    level                  = "ALL"
    log_destination        = "${aws_cloudwatch_log_group.agent_workflow.arn}:*"
  }

  tracing_configuration {
    enabled = true
  }
}

resource "aws_cloudwatch_metric_alarm" "agent_workflow" {
  for_each            = toset(["ExecutionsFailed", "ExecutionsTimedOut"])
  alarm_name          = "${var.name}-agent-workflow-${lower(each.value)}"
  alarm_description   = "Runbook RB-04: durable agent workflow did not reach a controlled terminal state"
  namespace           = "AWS/States"
  metric_name         = each.value
  dimensions          = { StateMachineArn = aws_sfn_state_machine.agents.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
