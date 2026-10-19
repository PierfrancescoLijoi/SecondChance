variable "name" {
  type        = string
  description = "Prefix of every resource, e.g. secondchance-demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.name))
    error_message = "Lowercase letters, digits and dashes, 3-21 characters."
  }
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["demo", "pilot"], var.environment)
    error_message = "demo (ephemeral, synthetic data) or pilot."
  }
}

variable "region" {
  type    = string
  default = "eu-central-1" # ADR-002
}

variable "image_tag" {
  type        = string
  description = "Immutable tag pushed by scripts/deploy.sh; images are <tag>-api, <tag>-worker and <tag>-gateway"
}

variable "alarm_email" {
  type        = string
  description = "Receives alarms and budget alerts"
}

variable "monthly_budget_usd" {
  type    = number
  default = 30 # an alert, not a hard stop (PRD section 6)
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "interface_endpoints" {
  type        = list(string)
  description = "PrivateLink services the Lambdas reach without a NAT gateway (ADR-006)"
  default     = ["sqs", "bedrock-runtime", "secretsmanager", "lambda", "states"]
}

variable "aurora_engine_version" {
  type        = string
  default     = "16.6"
  description = "Must support Serverless v2 with 0 ACU (auto-pause); verify with aws rds describe-db-engine-versions"
}

variable "aurora_min_acu" {
  type    = number
  default = 0
}

variable "aurora_max_acu" {
  type    = number
  default = 4
}

variable "aurora_instances" {
  type    = number
  default = 1 # 2 for the pilot: one reader in the second AZ
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  type    = bool
  default = false
}

variable "force_destroy" {
  type        = bool
  default     = false
  description = "Let terraform destroy empty versioned buckets: true only for the ephemeral demo"
}

variable "api_reserved_concurrency" {
  type        = number
  default     = 10
  nullable    = true
  description = "Caps database connections without RDS Proxy (ADR-006); null reserves nothing (accounts below 1,000 concurrency)"
}

variable "mcp_gateway_reserved_concurrency" {
  type        = number
  default     = 5
  nullable    = true
  description = "Independent MCP gateway bulkhead; protects the executor, Aurora and Bedrock; null reserves nothing"
  validation {
    condition     = var.mcp_gateway_reserved_concurrency == null ? true : (var.mcp_gateway_reserved_concurrency >= 1 && var.mcp_gateway_reserved_concurrency <= 50)
    error_message = "Use a bounded MCP gateway concurrency between 1 and 50."
  }
}

variable "requeue_schedule" {
  type        = string
  default     = "rate(2 minutes)"
  description = "Recovery of lost messages, expired leases and undispatched agent runs; every run opens a database connection"
}

variable "otel_exporter_otlp_endpoint" {
  type        = string
  default     = ""
  description = "Optional ADOT/OTLP HTTP endpoint; empty keeps application OTLP export disabled while Lambda X-Ray remains active"
}

variable "llm_mode" {
  type    = string
  default = "bedrock"
  validation {
    condition     = contains(["bedrock", "none"], var.llm_mode)
    error_message = "bedrock or none (extractive answers only)."
  }
}

variable "router_mode" {
  type        = string
  default     = "hybrid"
  description = "Safety-first request router: deterministic baseline, Bedrock-only, hybrid cascade, or optional Rizzo Flow"
  validation {
    condition     = contains(["baseline", "bedrock", "hybrid", "rizzo_flow"], var.router_mode)
    error_message = "baseline, bedrock, hybrid or rizzo_flow."
  }
}

variable "router_url" {
  type        = string
  default     = ""
  description = "Optional primary Rizzo Flow URL; it must be privately reachable from the VPC"
}

variable "router_shadow_url" {
  type        = string
  default     = ""
  description = "Optional privately reachable Rizzo Flow challenger URL; decisions are recorded but never executed"
}

variable "bedrock_model_id" {
  type        = string
  default     = "eu.anthropic.claude-haiku-5-5"
  description = "EU geographic inference profile; keeps inference within supported EU regions (ADR-002)"

  validation {
    condition     = startswith(var.bedrock_model_id, "eu.")
    error_message = "The pilot must use an eu.* Bedrock inference profile to preserve EU data residency."
  }
}

variable "cognito_tier" {
  type    = string
  default = "ESSENTIALS"
}

variable "enable_waf" {
  type    = bool
  default = true
}

variable "upload_limit_bytes" {
  type        = number
  default     = 4194304
  description = "API Gateway + Lambda cap request payloads at 6 MB and base64 grows binaries by a third"
}

variable "notification_sender_email" {
  type        = string
  default     = ""
  description = "Verified SES sender of mission emails (FR-026); empty uses alarm_email. SES sends it a verification link on apply"
  validation {
    condition     = var.notification_sender_email == "" || can(regex("^[^@<> ]+@[^@<> ]+\\.[^@<> ]+$", var.notification_sender_email))
    error_message = "A plain email address, without a display name."
  }
}

variable "guardduty_detector" {
  type        = bool
  default     = true
  description = "Create the account's GuardDuty detector; false when it already exists (one per region) or an organisation manages it"
}

variable "trail_retention_days" {
  type        = number
  default     = 365
  description = "Days the CloudTrail log files stay in their bucket (docs/compliance/gdpr.md)"
}
