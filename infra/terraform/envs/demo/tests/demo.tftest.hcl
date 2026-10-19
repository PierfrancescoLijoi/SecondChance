# Offline evaluation of the whole demo stack with mocked providers and realistic AWS values:
#   terraform -chdir=infra/terraform/envs/demo init -backend=false && terraform -chdir=infra/terraform/envs/demo test
# It catches what validate cannot: evaluated expressions, Lambda limits and the plan-time guards.

mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"}}]}" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["eu-central-1a", "eu-central-1b", "eu-central-1c"] }
  }
  mock_data "aws_vpc_endpoint_service" {
    defaults = { availability_zones = ["eu-central-1a", "eu-central-1b", "eu-central-1c"], service_name = "com.amazonaws.eu-central-1.service" }
  }
  mock_resource "aws_rds_cluster" {
    defaults = {
      id                  = "secondchance-demo"
      endpoint            = "secondchance-demo.cluster-c9akciq32lcd.eu-central-1.rds.amazonaws.com"
      cluster_resource_id = "cluster-ABCDEFGHIJKLMNOPQRSTUVWXY0"
      master_user_secret  = [{ secret_arn = "arn:aws:secretsmanager:eu-central-1:123456789012:secret:rds!cluster-0a1b2c3d-4e5f-6789-abcd-ef0123456789-AbCdEf", kms_key_id = "k", secret_status = "active" }]
    }
  }
  mock_resource "aws_db_proxy" {
    defaults = {
      arn      = "arn:aws:rds:eu-central-1:123456789012:db-proxy:prx-0123456789abcdef0"
      endpoint = "secondchance-demo.proxy-0123456789.eu-central-1.rds.amazonaws.com"
    }
  }
  mock_resource "aws_cognito_user_pool" {
    defaults = { id = "eu-central-1_AbCdEfGhI" }
  }
  mock_resource "aws_cognito_user_pool_client" {
    defaults = { id = "1example23456789abcdefghij" }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = { domain_name = "d1234abcd5678e.cloudfront.net", arn = "arn:aws:cloudfront::123456789012:distribution/E1ABCDEFGHIJKL" }
  }
  mock_resource "aws_bedrock_guardrail" {
    defaults = { guardrail_id = "abcd1234efgh", guardrail_arn = "arn:aws:bedrock:eu-central-1:123456789012:guardrail/abcd1234efgh" }
  }
  mock_resource "aws_bedrock_guardrail_version" {
    defaults = { version = "1" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:eu-central-1:123456789012:key/0a1b2c3d-4e5f-6789-abcd-ef0123456789", key_id = "0a1b2c3d-4e5f-6789-abcd-ef0123456789" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:eu-central-1:123456789012:log-group:/aws/secondchance" }
  }
  mock_resource "aws_cloudfront_function" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:function/secondchance-demo" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:eu-central-1:123456789012:secondchance-demo-alarms" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/secondchance-demo" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/secondchance-demo" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = { arn = "arn:aws:sqs:eu-central-1:123456789012:secondchance-demo", url = "https://sqs.eu-central-1.amazonaws.com/123456789012/secondchance-demo" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:eu-central-1:123456789012:function:secondchance-demo", invoke_arn = "arn:aws:apigateway:eu-central-1:lambda:path/2015-03-31/functions/arn:aws:lambda:eu-central-1:123456789012:function:secondchance-demo-api/invocations" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::secondchance-demo-123456789012", bucket_regional_domain_name = "secondchance-demo-web-123456789012.s3.eu-central-1.amazonaws.com" }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = { execution_arn = "arn:aws:execute-api:eu-central-1:123456789012:a1b2c3d4e5", api_endpoint = "https://a1b2c3d4e5.execute-api.eu-central-1.amazonaws.com" }
  }
  mock_resource "aws_dynamodb_table" {
    defaults = { arn = "arn:aws:dynamodb:eu-central-1:123456789012:table/secondchance-demo-mcp-rate-limit" }
  }
  mock_resource "aws_cognito_user_pool_domain" {
    defaults = { cloudfront_distribution = "d3abcdefghijk.cloudfront.net" }
  }
  mock_resource "aws_vpc_endpoint" {
    defaults = { prefix_list_id = "pl-6ea54007", id = "vpce-0123456789abcdef0" }
  }
  mock_resource "aws_security_group" {
    defaults = { id = "sg-0123456789abcdef0", arn = "arn:aws:ec2:eu-central-1:123456789012:security-group/sg-0123456789abcdef0" }
  }
  mock_resource "aws_subnet" {
    defaults = { id = "subnet-0123456789abcdef0" }
  }
  mock_resource "aws_vpc" {
    defaults = { id = "vpc-0123456789abcdef0" }
  }
  mock_resource "aws_route_table" {
    defaults = { id = "rtb-0123456789abcdef0" }
  }
  mock_resource "aws_scheduler_schedule" {
    defaults = { arn = "arn:aws:scheduler:eu-central-1:123456789012:schedule/default/secondchance-demo" }
  }
  mock_resource "aws_db_proxy_default_target_group" {
    defaults = { name = "default" }
  }
  mock_resource "aws_sfn_state_machine" {
    defaults = { arn = "arn:aws:states:eu-central-1:123456789012:stateMachine:secondchance-demo-agents" }
  }
  mock_resource "aws_ecr_repository" {
    defaults = { repository_url = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/secondchance-demo" }
  }
}

mock_provider "aws" {
  alias = "us_east_1"
  mock_resource "aws_wafv2_web_acl" {
    defaults = { arn = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/secondchance-demo/0a1b2c3d-4e5f-6789-abcd-ef0123456789" }
  }
}

mock_provider "http" {
  mock_data "http" {
    defaults = {
      status_code   = 200
      response_body = <<-JWKS
        {"keys":[{"kty":"RSA","key_ops":["verify"],"n":"2auy6Orf6NBmEcqfABS7x9c8a3Oa6QJnwhy2o3HbuBtnagX9PcwYJ7biLz9A18nMNouqWpDI0dYWHF0MH1Oc3YCFFgGkYpE3hpzZCXPg7XMkL41yq6HTjJsL9y-qYWOOooytO4i1RyxFLzjTxXXIXnvXJFJIiF6qbGGVRJHeuY3Ru68QVhzwyc55hG_SYEKGAPDfzpoTayuKAGv9OGO3R-5g85csCdZJu01qG9C-cYm8RDn6XJlRGPe64f_IOHD0ayBoFjRayo-HjtCLLCs9c1uLan2QAQ51x_PsoFMAy-V_rXOYqmoNgWHf4QDdRjWzRc93RWqxTu-q6EIfCv_KqQ","e":"AQAB","alg":"RS256","kid":"7xQm2fKpLr9VtYwZ3aBcDeFgHiJkLmNoPqRsTuVwXy0=","use":"sig"},{"kty":"RSA","key_ops":["verify"],"n":"u_C5ijbRmTuXHNWFIxGDayCVkRMAY-BXQaLC6rRi8gLUo7_0xPCejBcojXvU2n1cuB4OzQefgkXRiw1NT3JbW-XS0_t1q7l3xORl4rV5qWT6j4ks3wEbIO3xeewJ-F-UqEAzI_DmEoha6sgaTlW_SZBqqpNwYYyPfkraPDeej_ichSdKulfUGqvYeiSgjq-kklC4Wn-hvdncc1FzAf-SJbr_hFC0clWdoTWOVBxZsOcepFB8fH8i8JG7cW8xoZRh_RqoQ9lz3Ru0DppCjsOHmtImyRb5Ow1mHj60E1bJPCo3x2BeR1r9HvgjVeZaoPbi5_rKfsakRW5BSMrSS9cMHQ","e":"AQAB","alg":"RS256","kid":"Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1Wx2Yz3Ab4c=","use":"sig"}]}
      JWKS
    }
  }
}

variables {
  image_tag   = "0123456789ab-dirty-1792300000"
  alarm_email = "alarms@example.org"
}

run "demo_stack_fits_lambda_and_account_limits" {
  command = apply

  # Lambda: all environment variables of one function together must stay within 4 KB.
  assert {
    condition     = alltrue([for name, fn in module.secondchance.functions : length(jsonencode(fn.environment)) < 4096])
    error_message = "A Lambda environment exceeds 4 KB: ${jsonencode({ for name, fn in module.secondchance.functions : name => length(jsonencode(fn.environment)) })}"
  }
  assert {
    condition     = jsondecode(module.secondchance.functions["api"].environment.SECONDCHANCE_COGNITO_JWKS).keys[0].kty == "RSA"
    error_message = "The API must receive the Cognito signing keys at deploy time."
  }
  assert {
    condition     = alltrue([for name, fn in module.secondchance.functions : contains(["api", "realtime-authorizer"], name) || !contains(keys(fn.environment), "SECONDCHANCE_COGNITO_JWKS")])
    error_message = "Only the HTTP API and WebSocket authorizer verify tokens."
  }
  # A fresh account starts at 10 concurrent executions and Lambda keeps 100 unreserved.
  assert {
    condition     = alltrue([for fn in module.secondchance.functions : fn.reserved_concurrency == -1 || fn.reserved_concurrency == null])
    error_message = "The demo must not reserve Lambda concurrency."
  }
  assert {
    condition     = module.secondchance.schedules["requeue"] == "rate(1 hour)"
    error_message = "The demo requeues hourly."
  }
  assert {
    condition     = alltrue([for fn in module.secondchance.functions : endswith(fn.image_uri, "-api") || endswith(fn.image_uri, "-worker") || endswith(fn.image_uri, "-gateway")])
    error_message = "Every function must use one of the three pushed images."
  }
  # FR-026: mission emails through Cognito + SES from the verified sender (alarm email by default).
  assert {
    condition = (module.secondchance.functions["notifier"].environment.SECONDCHANCE_MAILER == "ses"
      && module.secondchance.functions["notifier"].environment.SECONDCHANCE_NOTIFY_DIRECTORY == "cognito"
      && module.secondchance.functions["notifier"].environment.SECONDCHANCE_MAIL_FROM == "alarms@example.org"
    && module.secondchance.notification_sender == "alarms@example.org")
    error_message = "The notifier must send through SES from the configured sender and resolve recipients in Cognito."
  }
  assert {
    condition     = alltrue([for name in ["api", "requeue", "jobs"] : contains(keys(module.secondchance.functions[name].environment), "SECONDCHANCE_QUEUE_NOTIFY")])
    error_message = "The API and the recovery job hand emails to the notify queue."
  }
}
