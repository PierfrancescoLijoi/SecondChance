# Fail fast at the edge (ADR-016 on Azure): one Front Door endpoint is the browser's only origin, the app
# at / and the API under /api, so no CORS is needed. The WAF and its rate limit run first; the API's
# containers then answer 403 to anything that did not come through this profile (secondchance.edge): the
# documented way to lock an origin, because the inbound traffic of an external Container Apps environment
# cannot be filtered by a network security group. Token validation
# happens in the API before any database use; unlike API Gateway's JWT authorizer it is not an edge feature.

locals {
  web_config = jsonencode({
    apiUrl       = "/api"
    authMode     = "oidc"
    realtimeMode = "negotiate"
    oidc = {
      authority = local.oidc_issuer
      clientId  = local.oidc_client_id
      scope     = "openid profile email api://${local.oidc_client_id}/access_as_user"
    }
  })
  premium_edge = var.front_door_sku == "Premium_AzureFrontDoor"
}

resource "azurerm_cdn_frontdoor_profile" "main" {
  name                     = "afd-${var.name}"
  resource_group_name      = azurerm_resource_group.main.name
  sku_name                 = var.front_door_sku
  response_timeout_seconds = 120
  tags                     = local.tags
}

resource "azurerm_cdn_frontdoor_endpoint" "main" {
  name                     = "${var.name}-${local.suffix}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
  tags                     = local.tags
}

# One origin per group, so there is no health probe: with scale to zero a probe would keep the apps awake.
resource "azurerm_cdn_frontdoor_origin_group" "main" {
  for_each                 = toset(["web", "api"])
  name                     = each.key
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id

  load_balancing {
    additional_latency_in_milliseconds = 50
    sample_size                        = 4
    successful_samples_required        = 3
  }
}

resource "azurerm_cdn_frontdoor_origin" "main" {
  for_each                       = toset(["web", "api"])
  name                           = each.key
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.main[each.key].id
  enabled                        = true
  host_name                      = azurerm_container_app.main[each.key].ingress[0].fqdn
  origin_host_header             = azurerm_container_app.main[each.key].ingress[0].fqdn
  certificate_name_check_enabled = true
  http_port                      = 80
  https_port                     = 443
  priority                       = 1
  weight                         = 1000
}

# --- rules: security headers everywhere, /api stripped before it reaches the API ---------------------------

resource "azurerm_cdn_frontdoor_rule_set" "security" {
  name                     = "security"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
}

resource "azurerm_cdn_frontdoor_rule" "security_headers" {
  name                      = "headers"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.security.id
  order                     = 1
  behavior_on_match         = "Continue"

  actions {
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Strict-Transport-Security"
      value         = "max-age=63072000; includeSubDomains; preload"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "X-Content-Type-Options"
      value         = "nosniff"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "X-Frame-Options"
      value         = "DENY"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Referrer-Policy"
      value         = "strict-origin-when-cross-origin"
    }
  }
}

resource "azurerm_cdn_frontdoor_rule_set" "api" {
  name                     = "api"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
}

resource "azurerm_cdn_frontdoor_rule" "strip_api" {
  name                      = "stripapi"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.api.id
  order                     = 1
  behavior_on_match         = "Continue"

  actions {
    url_rewrite_action {
      source_pattern          = "/api/"
      destination             = "/"
      preserve_unmatched_path = true
    }
  }
}

resource "azurerm_cdn_frontdoor_route" "api" {
  name                          = "api"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.main.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.main["api"].id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.main["api"].id]
  cdn_frontdoor_rule_set_ids    = [azurerm_cdn_frontdoor_rule_set.security.id, azurerm_cdn_frontdoor_rule_set.api.id]
  patterns_to_match             = ["/api/*"]
  supported_protocols           = ["Https"]
  forwarding_protocol           = "HttpsOnly"
  https_redirect_enabled        = false
  link_to_default_domain        = true
  # No cache block: API responses are never cached.

  depends_on = [azurerm_cdn_frontdoor_rule.security_headers, azurerm_cdn_frontdoor_rule.strip_api]
}

resource "azurerm_cdn_frontdoor_route" "web" {
  name                          = "web"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.main.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.main["web"].id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.main["web"].id]
  cdn_frontdoor_rule_set_ids    = [azurerm_cdn_frontdoor_rule_set.security.id]
  patterns_to_match             = ["/*"]
  supported_protocols           = ["Http", "Https"]
  forwarding_protocol           = "HttpsOnly"
  https_redirect_enabled        = true
  link_to_default_domain        = true

  # The app's own files are cached at the edge; /config.json and index.html answer with no-cache from nginx.
  cache {
    query_string_caching_behavior = "IgnoreQueryString"
    compression_enabled           = true
    content_types_to_compress     = ["text/html", "text/css", "application/javascript", "text/javascript", "application/json", "image/svg+xml"]
  }

  depends_on = [azurerm_cdn_frontdoor_rule.security_headers]
}

# --- WAF ---------------------------------------------------------------------------------------------

resource "azurerm_cdn_frontdoor_firewall_policy" "main" {
  name                = "${local.compact}waf"
  resource_group_name = azurerm_resource_group.main.name
  sku_name            = var.front_door_sku
  enabled             = true
  mode                = var.waf_mode
  tags                = local.tags

  # Per client address, before any container wakes up (AWS: 1000 requests per 5 minutes).
  custom_rule {
    name                           = "RatePerIp"
    enabled                        = true
    priority                       = 100
    type                           = "RateLimitRule"
    action                         = "Block"
    rate_limit_duration_in_minutes = 1
    rate_limit_threshold           = var.waf_rate_limit_per_minute

    match_condition {
      match_variable     = "RemoteAddr"
      operator           = "IPMatch"
      negation_condition = true # everything except the broadcast address, i.e. every client
      match_values       = ["255.255.255.255/32"]
    }
  }

  # Managed rule sets exist on the Premium tier only. If a legitimate PDF upload is blocked, read
  # FrontDoorWebApplicationFirewallLog and add an override for that rule rather than leaving Prevention.
  dynamic "managed_rule" {
    for_each = local.premium_edge ? { Microsoft_DefaultRuleSet = "2.1", Microsoft_BotManagerRuleSet = "1.1" } : {}
    content {
      type    = managed_rule.key
      version = managed_rule.value
      action  = "Block"
    }
  }
}

resource "azurerm_cdn_frontdoor_security_policy" "main" {
  name                     = "${var.name}-waf"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id

  security_policies {
    firewall {
      cdn_frontdoor_firewall_policy_id = azurerm_cdn_frontdoor_firewall_policy.main.id

      association {
        patterns_to_match = ["/*"]
        domain {
          cdn_frontdoor_domain_id = azurerm_cdn_frontdoor_endpoint.main.id
        }
      }
    }
  }
}
