# Plan-time guard (network.tf): an interface endpoint that AWS does not offer in one of the two
# chosen AZs must stop the plan before anything is created.
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
    defaults = { availability_zones = ["eu-central-1c"], service_name = "com.amazonaws.eu-central-1.service" }
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

run "endpoint_outside_the_chosen_zones_stops_the_plan" {
  command         = plan
  expect_failures = [data.aws_vpc_endpoint_service.interface]
}
