# API Gateway WebSocket API: authenticated on $connect, then used only for
# server-pushed run progress and streamed result events.

resource "aws_dynamodb_table" "realtime" {
  name         = "${var.name}-realtime-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connection_id"

  attribute {
    name = "connection_id"
    type = "S"
  }
  attribute {
    name = "run_id"
    type = "S"
  }
  global_secondary_index {
    name            = "run_id-index"
    projection_type = "KEYS_ONLY"
    key_schema {
      attribute_name = "run_id"
      key_type       = "HASH"
    }
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery {
    enabled = var.environment == "pilot"
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.main.arn
  }
}

resource "aws_apigatewayv2_api" "realtime" {
  name                       = "${var.name}-realtime"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
}

resource "aws_apigatewayv2_authorizer" "realtime" {
  api_id           = aws_apigatewayv2_api.realtime.id
  name             = "cognito-websocket"
  authorizer_type  = "REQUEST"
  authorizer_uri   = "arn:${local.partition}:apigateway:${var.region}:lambda:path/2015-03-31/functions/${aws_lambda_function.fn["realtime-authorizer"].arn}/invocations"
  identity_sources = ["route.request.header.Sec-WebSocket-Protocol"]
}

resource "aws_apigatewayv2_integration" "realtime" {
  api_id                 = aws_apigatewayv2_api.realtime.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn["realtime"].invoke_arn
  integration_method     = "POST"
  payload_format_version = "1.0"
  timeout_milliseconds   = 15000
}

resource "aws_apigatewayv2_route" "realtime" {
  for_each  = toset(["$connect", "$disconnect", "$default"])
  api_id    = aws_apigatewayv2_api.realtime.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.realtime.id}"

  authorization_type = each.value == "$connect" ? "CUSTOM" : "NONE"
  authorizer_id      = each.value == "$connect" ? aws_apigatewayv2_authorizer.realtime.id : null
}

resource "aws_cloudwatch_log_group" "realtime_access" {
  name              = "/aws/apigateway/${var.name}-realtime"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.main.arn
}

# Unlike HTTP APIs, WebSocket stages write logs only through the API Gateway account-level
# CloudWatch role (one per account and Region). Setting it is idempotent.
data "aws_iam_policy_document" "api_gateway_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["apigateway.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api_gateway_logs" {
  name               = "${var.name}-api-gateway-logs"
  assume_role_policy = data.aws_iam_policy_document.api_gateway_trust.json
}

resource "aws_iam_role_policy_attachment" "api_gateway_logs" {
  role       = aws_iam_role.api_gateway_logs.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "main" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_logs.arn
  depends_on          = [aws_iam_role_policy_attachment.api_gateway_logs]
}

resource "aws_apigatewayv2_stage" "realtime" {
  api_id      = aws_apigatewayv2_api.realtime.id
  name        = "realtime"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.realtime_access.arn
    format = jsonencode({
      requestId    = "$context.requestId", routeKey = "$context.routeKey", status = "$context.status",
      connectionId = "$context.connectionId", integrationError = "$context.integrationErrorMessage"
    })
  }
  depends_on = [aws_api_gateway_account.main]
}

resource "aws_lambda_permission" "realtime_authorizer" {
  statement_id  = "AllowRealtimeAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["realtime-authorizer"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.realtime.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.realtime.id}"
}

resource "aws_lambda_permission" "realtime_routes" {
  statement_id  = "AllowRealtimeRoutes"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["realtime"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.realtime.execution_arn}/*"
}

locals {
  # Keep these derived from the API only. Referring to the stage here creates a
  # Lambda -> stage -> route -> Lambda dependency cycle through common_env.
  realtime_url                 = "wss://${aws_apigatewayv2_api.realtime.id}.execute-api.${var.region}.amazonaws.com/realtime"
  realtime_management_endpoint = "https://${aws_apigatewayv2_api.realtime.id}.execute-api.${var.region}.amazonaws.com/realtime"
}
