output "web_url" {
  value = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "migrate_function" {
  value = aws_lambda_function.fn["migrate"].function_name
}

output "web_bucket" {
  value = aws_s3_bucket.web.bucket
}

output "distribution_id" {
  value = aws_cloudfront_distribution.main.id
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "hosted_ui_domain" {
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
}

output "agent_state_machine_arn" {
  value = aws_sfn_state_machine.agents.arn
}

output "realtime_url" {
  value = local.realtime_url
}

output "rds_proxy_endpoint" {
  value = aws_db_proxy.main.endpoint
}

output "functions" {
  description = "Each Lambda function's name, image, reserved concurrency and environment (operators, offline tests)"
  value = { for key, fn in aws_lambda_function.fn : key => {
    name                 = fn.function_name
    image_uri            = fn.image_uri
    reserved_concurrency = fn.reserved_concurrent_executions
    environment          = fn.environment[0].variables
  } }
}

output "schedules" {
  value = { for key, schedule in aws_scheduler_schedule.maintenance : key => schedule.schedule_expression }
}

output "notification_sender" {
  description = "SES identity mission emails come from; it must be verified (link sent by SES on the first apply)"
  value       = aws_sesv2_email_identity.sender.email_identity
}
