# One-off, per AWS account (ADR-018). Run once with an administrator SSO session:
#   aws sso login --profile secondchance-admin
#   terraform -chdir=infra/terraform/bootstrap init && terraform -chdir=infra/terraform/bootstrap apply \
#     -var github_repository=<owner>/<repo>
# Creates the Terraform state bucket and the role GitHub Actions assumes with OIDC.
# No access key is ever created.

terraform {
  required_version = ">= 1.16"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.66" }
  }
}

variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "github_repository" {
  type        = string
  default     = ""
  description = "owner/name of the repository allowed to deploy, through its 'production' environment only"
  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use the owner/name form."
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "secondchance", managed_by = "terraform", stack = "bootstrap" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# --- Terraform state: versioned, encrypted, private, TLS only; native S3 locking ---

resource "aws_s3_bucket" "state" {
  bucket = "secondchance-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_kms_key" "state" {
  description             = "SecondChance Terraform state"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 90 }
  }
}

# --- GitHub Actions: short-lived credentials through OIDC, one repository, one environment ---

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_repository == "" ? 0 : 1
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# Broad rights to build the stack, with a ceiling: the boundary forbids long-lived
# credentials, account or organization changes, and lifting the boundary itself.
resource "aws_iam_policy" "deploy_boundary" {
  count = var.github_repository == "" ? 0 : 1
  name  = "secondchance-deploy-boundary"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "AllowWithinBoundary", Effect = "Allow", Action = "*", Resource = "*" },
      {
        Sid    = "NoLongLivedCredentialsOrAccountChanges"
        Effect = "Deny"
        Action = [
          "iam:CreateUser", "iam:CreateAccessKey", "iam:CreateLoginProfile", "iam:UpdateLoginProfile",
          "organizations:*", "account:*", "billing:*",
          "iam:DeleteRolePermissionsBoundary", "iam:PutRolePermissionsBoundary",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role" "deploy" {
  count                = var.github_repository == "" ? 0 : 1
  name                 = "secondchance-github-deploy"
  max_session_duration = 3600
  permissions_boundary = aws_iam_policy.deploy_boundary[0].arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github[0].arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:production" }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "deploy" {
  count      = var.github_repository == "" ? 0 : 1
  role       = aws_iam_role.deploy[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AdministratorAccess"
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "deploy_role_arn" {
  description = "Set it as the GitHub variable AWS_DEPLOY_ROLE_ARN of the 'production' environment"
  value       = try(aws_iam_role.deploy[0].arn, null)
}
