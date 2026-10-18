terraform {
  required_version = ">= 1.16"
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      version               = "~> 6.66"
      configuration_aliases = [aws.us_east_1] # CloudFront-scoped WAF lives in us-east-1
    }
    http = { source = "hashicorp/http", version = "~> 3.5" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  queues = {
    jobs            = { visibility = 1800 } # >= 6x the worker timeout, as AWS recommends for SQS sources
    notify          = { visibility = 300 }
    realtime-events = { visibility = 90 }
  }
}

# One key for data at rest: Aurora, the master secret, S3 objects, logs (NFR-001).
resource "aws_kms_key" "main" {
  description             = "${var.name} data at rest"
  enable_key_rotation     = true
  deletion_window_in_days = var.environment == "demo" ? 7 : 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AlarmsAndBudgetsToEncryptedTopic"
        Effect    = "Allow"
        Principal = { Service = ["cloudwatch.amazonaws.com", "budgets.amazonaws.com"] }
        Action    = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.region}.amazonaws.com" }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
      },
    ]
  })
}

resource "aws_kms_alias" "main" {
  name          = "alias/${var.name}"
  target_key_id = aws_kms_key.main.key_id
}
