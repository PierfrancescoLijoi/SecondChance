# Detective controls (detection.tf, ADR-022): the trail, the malware scan of uploads and the rules
# that act on its verdict, evaluated offline with mocked providers.
#   terraform -chdir=infra/terraform/modules/secondchance init -backend=false && ... test

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
}

mock_provider "aws" {
  alias = "us_east_1"
}

mock_provider "http" {
  mock_data "http" {
    defaults = { status_code = 200, response_body = "{\"keys\":[{\"kty\":\"RSA\",\"kid\":\"k1\"}]}" }
  }
}

variables {
  name        = "secondchance-demo"
  environment = "demo"
  image_tag   = "0123456789ab"
  alarm_email = "alarms@example.org"
}

run "uploads_are_scanned_and_infected_objects_unreadable" {
  command = plan

  override_resource {
    target          = aws_s3_bucket.objects
    override_during = plan
    values          = { arn = "arn:aws:s3:::secondchance-demo-objects-123456789012", id = "secondchance-demo-objects-123456789012" }
  }

  assert {
    condition     = aws_guardduty_malware_protection_plan.objects.protected_resource[0].s3_bucket[0].object_prefixes == toset(["tenants/"])
    error_message = "every tenant upload must be scanned"
  }
  assert {
    condition     = aws_guardduty_malware_protection_plan.objects.actions[0].tagging[0].status == "ENABLED"
    error_message = "the verdict tag is what the worker and the bucket policy act on"
  }
  assert {
    condition     = contains([for s in jsondecode(aws_s3_bucket_policy.objects.policy).Statement : s.Sid], "DenyInfectedObjects")
    error_message = "infected objects must be unreadable for every principal"
  }
  assert {
    condition     = aws_lambda_function.fn["jobs"].environment[0].variables["SECONDCHANCE_MALWARE_SCAN"] == "guardduty"
    error_message = "the jobs worker must wait for the verdict before parsing"
  }
}

run "the_trail_is_tamper_evident_and_encrypted" {
  command = plan

  assert {
    condition     = aws_cloudtrail.main.enable_log_file_validation && aws_cloudtrail.main.is_multi_region_trail
    error_message = "the trail covers every region and its files carry digests"
  }
  assert {
    condition     = one([for r in aws_s3_bucket_server_side_encryption_configuration.trail.rule : r.apply_server_side_encryption_by_default[0].sse_algorithm]) == "aws:kms"
    error_message = "trail files are encrypted with the customer key"
  }
  assert {
    condition     = contains([for s in jsondecode(aws_kms_key.main.policy).Statement : s.Sid], "CloudTrailEncryptsLogs")
    error_message = "CloudTrail needs the key policy grant, scoped to this trail"
  }
}

run "an_existing_detector_is_not_recreated" {
  command = plan
  variables { guardduty_detector = false }

  assert {
    condition     = length(aws_guardduty_detector.main) == 0 && length(aws_guardduty_detector_feature.main) == 0
    error_message = "one detector per region: an account that has one must not get a second"
  }
}
