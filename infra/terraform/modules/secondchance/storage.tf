# Two private buckets: application objects (documents, artifacts, under tenants/{id}/) and
# the web app served through CloudFront with Origin Access Control (ADR-011).

resource "aws_s3_bucket" "objects" {
  bucket        = "${var.name}-objects-${local.account_id}"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket" "web" {
  bucket        = "${var.name}-web-${local.account_id}"
  force_destroy = true # only build output: always rebuildable
}

resource "aws_s3_bucket_versioning" "objects" {
  bucket = aws_s3_bucket.objects.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}

# Built JavaScript, CSS and config.json only: public content, served through CloudFront OAC.
# trivy:ignore:AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "objects" {
  bucket                  = aws_s3_bucket.objects.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    id     = "housekeeping"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

resource "aws_s3_bucket_policy" "objects" {
  bucket = aws_s3_bucket.objects.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.objects.arn, "${aws_s3_bucket.objects.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        # GuardDuty tags infected uploads (detection.tf); nobody reads them, whatever their IAM role.
        Sid       = "DenyInfectedObjects"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource  = "${aws_s3_bucket.objects.arn}/*"
        Condition = { StringEquals = { "s3:ExistingObjectTag/GuardDutyMalwareScanStatus" = "THREATS_FOUND" } }
      },
    ]
  })
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "CloudFrontReadOnly"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.web.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.main.arn } }
    }]
  })
}

# Runtime configuration of the web app (web/src/config.ts): one build for every environment.
resource "aws_s3_object" "web_config" {
  bucket        = aws_s3_bucket.web.id
  key           = "config.json"
  content_type  = "application/json"
  cache_control = "no-store"
  content = jsonencode({
    apiUrl      = "/api"
    realtimeUrl = local.realtime_url
    authMode    = "oidc"
    oidc = {
      authority = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
      clientId  = aws_cognito_user_pool_client.web.id
      scope     = "openid email"
      # Cognito has no end_session_endpoint; logout_uri must equal one of the client's logout_urls.
      logoutUrl = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com/logout?client_id=${aws_cognito_user_pool_client.web.id}&logout_uri=${urlencode("https://${aws_cloudfront_distribution.main.domain_name}/")}"
    }
  })
}
