# One image repository, three isolated images (<tag>-api, <tag>-worker, <tag>-gateway).
# Each role reaches only the database user it needs (rds-db:connect) - no shared secret.

resource "aws_ecr_repository" "app" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.force_destroy
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 20 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}

locals {
  agent_state_machine_arn = "arn:${local.partition}:states:${var.region}:${local.account_id}:stateMachine:${var.name}-agents"
  common_env = merge({
    SECONDCHANCE_ENV                          = var.environment
    SECONDCHANCE_AUTH_MODE                    = "cognito"
    SECONDCHANCE_COGNITO_ISSUER               = local.cognito_issuer
    SECONDCHANCE_COGNITO_CLIENT_ID            = aws_cognito_user_pool_client.web.id
    SECONDCHANCE_DB_IAM_AUTH                  = "1"
    SECONDCHANCE_DATABASE_URL                 = local.db_url["secondchance_app"]
    SECONDCHANCE_S3_BUCKET                    = aws_s3_bucket.objects.bucket
    SECONDCHANCE_QUEUE_JOBS                   = aws_sqs_queue.main["jobs"].name
    SECONDCHANCE_QUEUE_NOTIFY                 = aws_sqs_queue.main["notify"].name
    SECONDCHANCE_AGENT_STATE_MACHINE_ARN      = local.agent_state_machine_arn
    SECONDCHANCE_REALTIME_TABLE               = aws_dynamodb_table.realtime.name
    SECONDCHANCE_REALTIME_QUEUE_URL           = aws_sqs_queue.main["realtime-events"].url
    SECONDCHANCE_REALTIME_MANAGEMENT_ENDPOINT = local.realtime_management_endpoint
    SECONDCHANCE_EMBEDDINGS                   = "bedrock"
    SECONDCHANCE_LLM                          = var.llm_mode
    SECONDCHANCE_BEDROCK_MODEL                = var.bedrock_model_id
    SECONDCHANCE_ROUTER_MODE                  = var.router_mode
    SECONDCHANCE_GUARDRAIL_ID                 = aws_bedrock_guardrail.main.guardrail_id
    SECONDCHANCE_GUARDRAIL_VERSION            = aws_bedrock_guardrail_version.main.version
    SECONDCHANCE_LIMIT_UPLOAD_BYTES           = tostring(var.upload_limit_bytes)
    SECONDCHANCE_LOG_LEVEL                    = "INFO"
    SECONDCHANCE_WEB_ORIGINS                  = "https://${aws_cloudfront_distribution.main.domain_name}"
    OTEL_SERVICE_NAME                         = "secondchance-${var.environment}"
    OTEL_RESOURCE_ATTRIBUTES                  = "deployment.environment=${var.environment},service.namespace=secondchance"
    }, var.router_url == "" ? {} : {
    SECONDCHANCE_ROUTER_URL = var.router_url
    }, var.router_shadow_url == "" ? {} : {
    SECONDCHANCE_ROUTER_SHADOW_URL = var.router_shadow_url
    }, var.otel_exporter_otlp_endpoint == "" ? {} : {
    OTEL_EXPORTER_OTLP_ENDPOINT = var.otel_exporter_otlp_endpoint
    OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
  })

  # name => image target, handler command, timeout, IAM role key, extra environment
  functions = {
    api             = { target = "api", command = null, timeout = 29, role = "api", memory = 1024, env = { SECONDCHANCE_COGNITO_JWKS = jsonencode(jsondecode(data.http.cognito_jwks.response_body)) } }
    "agent-step"    = { target = "worker", command = ["secondchance.aws_lambda.agent_step"], timeout = 300, role = "agent", memory = 1024, env = { SECONDCHANCE_MCP_GATEWAY_FUNCTION = "${var.name}-mcp-gateway" } }
    jobs            = { target = "worker", command = ["secondchance.aws_lambda.jobs"], timeout = 300, role = "app", memory = 2048, env = { SECONDCHANCE_MALWARE_SCAN = "guardduty" } }
    "demo-seed"     = { target = "worker", command = ["secondchance.aws_lambda.demo_seed"], timeout = 600, role = "app", memory = 2048, env = {} }
    "runtime-check" = { target = "worker", command = ["secondchance.aws_lambda.runtime_check"], timeout = 120, role = "agent", memory = 1024, env = { SECONDCHANCE_MCP_GATEWAY_FUNCTION = "${var.name}-mcp-gateway" } }
    "tool-executor" = { target = "worker", command = ["secondchance.aws_lambda.tool_executor"], timeout = 30, role = "app", memory = 1024, env = {} }
    "mcp-gateway" = {
      target = "gateway", command = ["mcp_gateway.lambda_handler.gateway"], timeout = 29, role = "gateway", memory = 512
      env = {
        SECONDCHANCE_TOOL_EXECUTOR_FUNCTION = "${var.name}-tool-executor"
        SECONDCHANCE_MCP_RATE_LIMIT_TABLE   = aws_dynamodb_table.mcp_rate_limit.name
      }
    }
    "realtime-authorizer" = { target = "worker", command = ["secondchance.aws_lambda.realtime_authorizer"], timeout = 10, role = "authorizer", memory = 256, public = true, env = { SECONDCHANCE_COGNITO_JWKS = jsonencode(jsondecode(data.http.cognito_jwks.response_body)) } }
    realtime = {
      target = "worker", command = ["secondchance.aws_lambda.realtime"], timeout = 15, role = "realtime", memory = 512, public = false
      env    = { SECONDCHANCE_REALTIME_TABLE = aws_dynamodb_table.realtime.name }
    }
    "realtime-publisher" = {
      target = "worker", command = ["secondchance.aws_lambda.realtime_publisher"], timeout = 15, role = "publisher", memory = 256, public = true
      env    = { SECONDCHANCE_REALTIME_TABLE = aws_dynamodb_table.realtime.name }
    }
    # FR-026: outside the VPC like the realtime relay (Cognito with a hosted domain has no PrivateLink),
    # with no data permission: it reads the notify queue, looks the address up in Cognito, sends with SES.
    notifier = {
      target = "worker", command = ["secondchance.aws_lambda.notifier"], timeout = 30, role = "notifier", memory = 256, public = true
      env = {
        SECONDCHANCE_NOTIFY_DIRECTORY     = "cognito"
        SECONDCHANCE_COGNITO_USER_POOL_ID = aws_cognito_user_pool.main.id
        SECONDCHANCE_MAILER               = "ses"
        SECONDCHANCE_MAIL_FROM            = local.notification_sender
        SECONDCHANCE_WEB_URL              = "https://${aws_cloudfront_distribution.main.domain_name}"
      }
    }
    retention = { target = "worker", command = ["secondchance.aws_lambda.retention"], timeout = 300, role = "maintenance", memory = 512, env = { SECONDCHANCE_MAINTENANCE_URL = local.db_url["secondchance_maintenance"] } }
    requeue   = { target = "worker", command = ["secondchance.aws_lambda.requeue"], timeout = 60, role = "maintenance", memory = 512, env = { SECONDCHANCE_MAINTENANCE_URL = local.db_url["secondchance_maintenance"] } }
    migrate = {
      target = "worker", command = ["secondchance.aws_lambda.migrate"], timeout = 600, role = "migrate", memory = 1024
      env = {
        SECONDCHANCE_MIGRATOR_URL         = local.db_url["secondchance_migrator"]
        SECONDCHANCE_DB_HOST              = local.db_cluster_host
        SECONDCHANCE_DB_MASTER_SECRET_ARN = aws_rds_cluster.main.master_user_secret[0].secret_arn
      }
    }
  }
}

# --- IAM: least privilege per family ---

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "function" {
  for_each           = toset(["agent", "api", "app", "authorizer", "gateway", "maintenance", "migrate", "notifier", "publisher", "realtime"])
  name               = "${var.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "vpc" {
  for_each   = aws_iam_role.function
  role       = each.value.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "xray" {
  for_each   = aws_iam_role.function
  role       = each.value.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "DatabaseAsAppRole"
    actions   = ["rds-db:connect"]
    resources = [local.db_user_arn["secondchance_app"]]
  }
  statement {
    sid       = "Queues"
    actions   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ChangeMessageVisibility"]
    resources = [for q in aws_sqs_queue.main : q.arn]
  }
  statement {
    sid       = "Objects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:GetObjectTagging"] # tagging: the malware verdict (ADR-022)
    resources = ["${aws_s3_bucket.objects.arn}/tenants/*"]
  }
  statement {
    sid       = "ObjectsKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.main.arn]
  }
  statement {
    sid     = "ModelsAndGuardrail"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:ApplyGuardrail"]
    resources = [
      "arn:${local.partition}:bedrock:*::foundation-model/*",
      "arn:${local.partition}:bedrock:${var.region}:${local.account_id}:inference-profile/*",
      aws_bedrock_guardrail.main.guardrail_arn,
    ]
  }
}

data "aws_iam_policy_document" "api" {
  source_policy_documents = [data.aws_iam_policy_document.app.json]
  statement {
    sid       = "StartAgentWorkflow"
    actions   = ["states:StartExecution"]
    resources = [local.agent_state_machine_arn]
  }
}

data "aws_iam_policy_document" "agent" {
  source_policy_documents = [data.aws_iam_policy_document.app.json]
  statement {
    sid       = "InvokeMcpGateway"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:${local.partition}:lambda:${var.region}:${local.account_id}:function:${var.name}-mcp-gateway"]
  }
}

data "aws_iam_policy_document" "realtime" {
  source_policy_documents = [data.aws_iam_policy_document.dynamodb_kms.json]
  statement {
    sid       = "DatabaseAsAppRole"
    actions   = ["rds-db:connect"]
    resources = [local.db_user_arn["secondchance_app"]]
  }
  statement {
    sid       = "ManageSubscriptions"
    actions   = ["dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.realtime.arn]
  }
}

data "aws_iam_policy_document" "publisher" {
  source_policy_documents = [data.aws_iam_policy_document.dynamodb_kms.json]
  statement {
    sid       = "ConsumeRealtimeEvents"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.main["realtime-events"].arn]
  }
  statement {
    sid       = "ReadRealtimeSubscriptions"
    actions   = ["dynamodb:Query", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.realtime.arn, "${aws_dynamodb_table.realtime.arn}/index/run_id-index"]
  }
  statement {
    sid       = "ManageRealtimeConnections"
    actions   = ["execute-api:ManageConnections"]
    resources = ["${aws_apigatewayv2_api.realtime.execution_arn}/*/@connections/*"]
  }
}

data "aws_iam_policy_document" "notifier" {
  statement {
    sid       = "ConsumeNotifications"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.main["notify"].arn]
  }
  statement {
    sid       = "ResolveRecipientBySub"
    actions   = ["cognito-idp:ListUsers"]
    resources = [aws_cognito_user_pool.main.arn]
  }
  statement {
    # identity/* because SES also authorises against recipient identities while the account is in the
    # sandbox; the condition still allows only the configured sender.
    sid       = "SendFromTheConfiguredSenderOnly"
    actions   = ["ses:SendEmail"]
    resources = ["arn:${local.partition}:ses:${var.region}:${local.account_id}:identity/*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [local.notification_sender]
    }
  }
}

# DynamoDB encrypts the rate-limit and realtime tables with the main key on behalf of the caller.
data "aws_iam_policy_document" "dynamodb_kms" {
  statement {
    sid       = "TableKeyThroughDynamoDB"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = [aws_kms_key.main.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["dynamodb.${var.region}.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "gateway" {
  source_policy_documents = [data.aws_iam_policy_document.dynamodb_kms.json]
  statement {
    sid       = "InvokePrivateToolExecutor"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:${local.partition}:lambda:${var.region}:${local.account_id}:function:${var.name}-tool-executor"]
  }
  statement {
    sid       = "DistributedRateLimit"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.mcp_rate_limit.arn]
  }
}

data "aws_iam_policy_document" "maintenance" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [local.agent_state_machine_arn]
  }
  statement {
    actions   = ["states:DescribeExecution", "states:RedriveExecution"]
    resources = ["arn:${local.partition}:states:${var.region}:${local.account_id}:execution:${var.name}-agents:*"]
  }
  statement {
    actions   = ["rds-db:connect"]
    resources = [local.db_user_arn["secondchance_maintenance"]]
  }
  statement {
    # Lost ingestion and matching jobs go back to jobs; undelivered emails to notify (outbox).
    actions   = ["sqs:SendMessage", "sqs:GetQueueUrl"]
    resources = [aws_sqs_queue.main["jobs"].arn, aws_sqs_queue.main["notify"].arn]
  }
}

data "aws_iam_policy_document" "migrate" {
  statement {
    actions   = ["rds-db:connect"]
    resources = [local.db_user_arn["secondchance_migrator"]]
  }
  statement {
    sid       = "MasterSecretForRoleBootstrapOnly"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_rds_cluster.main.master_user_secret[0].secret_arn]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.main.arn]
  }
}

resource "aws_iam_role_policy" "function" {
  for_each = {
    agent       = data.aws_iam_policy_document.agent.json
    api         = data.aws_iam_policy_document.api.json
    app         = data.aws_iam_policy_document.app.json
    gateway     = data.aws_iam_policy_document.gateway.json
    maintenance = data.aws_iam_policy_document.maintenance.json
    migrate     = data.aws_iam_policy_document.migrate.json
    notifier    = data.aws_iam_policy_document.notifier.json
    publisher   = data.aws_iam_policy_document.publisher.json
    realtime    = data.aws_iam_policy_document.realtime.json
  }
  role   = aws_iam_role.function[each.key].name
  policy = each.value
}

# --- Functions ---

resource "aws_cloudwatch_log_group" "function" {
  for_each          = local.functions
  name              = "/aws/lambda/${var.name}-${each.key}"
  retention_in_days = 30 # ADR-014
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_lambda_function" "fn" {
  for_each      = local.functions
  function_name = "${var.name}-${each.key}"
  role          = aws_iam_role.function[each.value.role].arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}-${each.value.target}"
  timeout       = each.value.timeout
  memory_size   = each.value.memory
  architectures = ["x86_64"]

  reserved_concurrent_executions = each.key == "api" ? var.api_reserved_concurrency : (each.key == "mcp-gateway" ? var.mcp_gateway_reserved_concurrency : null)

  dynamic "image_config" {
    for_each = each.value.command == null ? [] : [each.value.command]
    content {
      command = image_config.value
    }
  }

  dynamic "vpc_config" {
    for_each = try(each.value.public, false) ? [] : [1]
    content {
      subnet_ids         = aws_subnet.private[*].id
      security_group_ids = [aws_security_group.lambda.id]
    }
  }

  environment {
    variables = merge(local.common_env, each.value.env)
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [aws_iam_role_policy_attachment.vpc, aws_iam_role_policy.function]

  logging_config {
    log_format = "Text" # the app already writes JSON lines
    log_group  = aws_cloudwatch_log_group.function[each.key].name
  }
}

resource "aws_lambda_event_source_mapping" "queue" {
  for_each                = { jobs = "jobs", notifier = "notify", "realtime-publisher" = "realtime-events" }
  event_source_arn        = aws_sqs_queue.main[each.value].arn
  function_name           = aws_lambda_function.fn[each.key].arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]
  scaling_config {
    # SQS/Lambda scales consumers from zero according to backlog; this ceiling is the
    # database/Bedrock bulkhead, configurable per environment (ADR-006).
    maximum_concurrency = 5
  }
}

# --- Scheduled maintenance (EventBridge Scheduler) ---

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = [aws_lambda_function.fn["retention"].arn, aws_lambda_function.fn["requeue"].arn]
    }]
  })
}

resource "aws_scheduler_schedule" "maintenance" {
  for_each = {
    retention = "cron(15 3 * * ? *)" # daily (ADR-014)
    requeue   = var.requeue_schedule # lost messages and expired leases (ADR-010, ADR-015)
  }
  name                = "${var.name}-${each.key}"
  schedule_expression = each.value
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.fn[each.key].arn
    role_arn = aws_iam_role.scheduler.arn
  }
}
