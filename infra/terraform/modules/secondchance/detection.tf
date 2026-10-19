# Detective controls (ADR-022, GDPR art. 32): an account trail with object-level events on the
# documents bucket, GuardDuty threat detection, and a malware scan of every upload before the jobs
# worker parses it. High-severity findings reach the alarm topic.

locals {
  trail_arn = "arn:${local.partition}:cloudtrail:${var.region}:${local.account_id}:trail/${var.name}"
}

# --- CloudTrail: management events everywhere, object events on tenant documents ---

resource "aws_s3_bucket" "trail" {
  bucket        = "${var.name}-trail-${local.account_id}"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_versioning" "trail" {
  bucket = aws_s3_bucket.trail.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket                  = aws_s3_bucket.trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    id     = "retention"
    status = "Enabled"
    filter {}
    expiration { days = var.trail_retention_days }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.trail.arn, "${aws_s3_bucket.trail.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "CloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.trail.arn
        Condition = { StringEquals = { "aws:SourceArn" = local.trail_arn } }
      },
      {
        Sid       = "CloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.trail.arn}/AWSLogs/${local.account_id}/*"
        Condition = { StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control", "aws:SourceArn" = local.trail_arn } }
      },
    ]
  })
}

resource "aws_cloudtrail" "main" {
  name                          = var.name
  s3_bucket_name                = aws_s3_bucket.trail.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  kms_key_id                    = aws_kms_key.main.arn

  event_selector {
    read_write_type           = "All"
    include_management_events = true
    data_resource {
      type   = "AWS::S3::Object"
      values = ["${aws_s3_bucket.objects.arn}/"] # who read or wrote which tenant document
    }
  }

  depends_on = [aws_s3_bucket_policy.trail]
}

# --- GuardDuty: threat detection on the account, S3 data events, Aurora logins, Lambda network ---

resource "aws_guardduty_detector" "main" {
  count                        = var.guardduty_detector ? 1 : 0
  enable                       = true
  finding_publishing_frequency = "FIFTEEN_MINUTES"
}

resource "aws_guardduty_detector_feature" "main" {
  for_each    = var.guardduty_detector ? toset(["S3_DATA_EVENTS", "RDS_LOGIN_EVENTS", "LAMBDA_NETWORK_LOGS"]) : toset([])
  detector_id = aws_guardduty_detector.main[0].id
  name        = each.value
  status      = "ENABLED"
}

# --- Malware Protection for S3: every upload is scanned and tagged with its verdict ---

data "aws_iam_policy_document" "malware_scan_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["malware-protection-plan.guardduty.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "malware_scan" {
  statement {
    sid       = "ManagedEventBridgeRule"
    actions   = ["events:PutRule", "events:DeleteRule", "events:PutTargets", "events:RemoveTargets"]
    resources = ["arn:${local.partition}:events:${var.region}:${local.account_id}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*"]
    condition {
      test     = "StringLike"
      variable = "events:ManagedBy"
      values   = ["malware-protection-plan.guardduty.amazonaws.com"]
    }
  }
  statement {
    sid       = "InspectManagedEventBridgeRule"
    actions   = ["events:DescribeRule", "events:ListTargetsByRule"]
    resources = ["arn:${local.partition}:events:${var.region}:${local.account_id}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*"]
  }
  statement {
    sid       = "BucketNotificationsAndOwnership"
    actions   = ["s3:PutBucketNotification", "s3:GetBucketNotification", "s3:ListBucket"]
    resources = [aws_s3_bucket.objects.arn]
  }
  statement {
    sid       = "ValidationObject"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.objects.arn}/malware-protection-resource-validation-object"]
  }
  statement {
    sid = "ScanAndTag"
    actions = ["s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectTagging", "s3:GetObjectVersionTagging",
    "s3:PutObjectTagging", "s3:PutObjectVersionTagging"]
    resources = ["${aws_s3_bucket.objects.arn}/tenants/*"]
  }
  statement {
    sid       = "DecryptObjects"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.main.arn]
    condition {
      test     = "StringLike"
      variable = "kms:ViaService"
      values   = ["s3.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "malware_scan" {
  name               = "${var.name}-malware-scan"
  assume_role_policy = data.aws_iam_policy_document.malware_scan_trust.json
}

resource "aws_iam_role_policy" "malware_scan" {
  role   = aws_iam_role.malware_scan.name
  policy = data.aws_iam_policy_document.malware_scan.json
}

resource "aws_guardduty_malware_protection_plan" "objects" {
  role = aws_iam_role.malware_scan.arn
  protected_resource {
    s3_bucket {
      bucket_name     = aws_s3_bucket.objects.id
      object_prefixes = ["tenants/"]
    }
  }
  actions {
    tagging { status = "ENABLED" } # GuardDutyMalwareScanStatus: read by the jobs worker, enforced by the bucket policy
  }
  depends_on = [aws_iam_role_policy.malware_scan]
}

# --- High-severity findings (including malicious uploads) to the alarm topic ---

resource "aws_cloudwatch_event_rule" "guardduty_findings" {
  name        = "${var.name}-guardduty-findings"
  description = "GuardDuty findings of severity 7 or more (runbook RB-11)"
  event_pattern = jsonencode({
    source        = ["aws.guardduty"]
    "detail-type" = ["GuardDuty Finding"]
    detail        = { severity = [{ numeric = [">=", 7] }] }
  })
}

resource "aws_cloudwatch_event_target" "guardduty_findings" {
  rule = aws_cloudwatch_event_rule.guardduty_findings.name
  arn  = aws_sns_topic.alarms.arn
}

resource "aws_sns_topic_policy" "alarms" {
  arn = aws_sns_topic.alarms.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountOwner"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = ["SNS:GetTopicAttributes", "SNS:SetTopicAttributes", "SNS:Subscribe", "SNS:ListSubscriptionsByTopic", "SNS:Publish"]
        Resource  = aws_sns_topic.alarms.arn
      },
      {
        Sid       = "CloudWatchAlarms"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.alarms.arn
        Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
      },
      {
        Sid       = "GuardDutyFindings"
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.alarms.arn
        Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.guardduty_findings.arn } }
      },
    ]
  })
}
