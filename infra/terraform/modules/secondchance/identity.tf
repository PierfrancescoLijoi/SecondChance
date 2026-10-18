# Cognito proves who the user is; SecondChance memberships decide what they may do (ADR-017).
# Self sign-up with email verification; the web app uses authorization code + PKCE.

resource "aws_cognito_user_pool" "main" {
  name                     = var.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OPTIONAL"
  deletion_protection      = var.deletion_protection ? "ACTIVE" : "INACTIVE"
  user_pool_tier           = var.cognito_tier

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  admin_create_user_config {
    allow_admin_create_user_only = false
  }
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.name}-${local.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
  # Classic hosted UI: managed login (2) shows no page for an app client created through the API
  # until a branding style exists, and this stack creates the client with Terraform.
  managed_login_version = 1
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${var.name}-web"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = false # public client: the browser cannot keep a secret
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://${aws_cloudfront_distribution.main.domain_name}/callback"]
  logout_urls                          = ["https://${aws_cloudfront_distribution.main.domain_name}/"]
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 7

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

locals {
  cognito_issuer = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

# The API verifies tokens offline with these keys. It runs in a VPC without NAT, and a user pool
# with a domain (needed by the hosted sign-in) is not reachable through PrivateLink. Cognito does
# not rotate user pool signing keys; every apply reads them again.
data "http" "cognito_jwks" {
  url             = "${local.cognito_issuer}/.well-known/jwks.json"
  request_headers = { Accept = "application/json" }
  retry {
    attempts     = 5
    min_delay_ms = 2000
  }
  lifecycle {
    postcondition {
      condition     = self.status_code == 200 && length(try(jsondecode(self.response_body).keys, [])) > 0
      error_message = "The Cognito user pool published no signing keys."
    }
  }
}
