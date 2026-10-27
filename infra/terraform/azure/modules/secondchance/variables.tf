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

variable "location" {
  type        = string
  default     = "germanywestcentral" # Frankfurt, like eu-central-1 on AWS (ADR-002)
  description = "Azure region. EU regions only: the pilot holds data about vulnerable people (ADR-002)."
  validation {
    condition = contains([
      "germanywestcentral", "swedencentral", "francecentral", "northeurope", "westeurope",
      "italynorth", "polandcentral", "spaincentral", "norwayeast", "switzerlandnorth",
    ], var.location)
    error_message = "Use an EU/EFTA region where the services below are offered."
  }
}

variable "image_tag" {
  type        = string
  description = "Immutable tag pushed by scripts/azure/deploy.sh; images are app:<tag>, gateway:<tag> and web:<tag>"
}

variable "alarm_email" {
  type        = string
  description = "Receives alarms and budget alerts"
}

variable "monthly_budget" {
  type        = number
  default     = 30
  description = "Monthly budget of the resource group in the billing currency; an alert, not a hard stop (PRD section 6)"
}

variable "vnet_cidr" {
  type    = string
  default = "10.50.0.0/16"
}

variable "nat_gateway" {
  type        = bool
  default     = false
  description = "Explicit, stable outbound address for the Container Apps subnet (pilot); the demo uses the platform default"
}

# --- identity -------------------------------------------------------------------------------

variable "create_app_registrations" {
  type        = bool
  default     = true
  description = "Create the Entra app registrations (web/API, MCP gateway, tool executor) and the app-role assignments. False when the deploying identity may not write to Entra: then set oidc_* and service-to-service calls rely on the private network only."
}

variable "oidc_client_id" {
  type        = string
  default     = ""
  description = "Existing app registration (create_app_registrations = false). Its tokens must be v2.0, carry oid and the scope access_as_user."
}

variable "oidc_issuer" {
  type        = string
  default     = ""
  description = "Token issuer override, e.g. https://<tenant>.ciamlogin.com/<tenant-id>/v2.0 for an Entra External ID tenant; empty derives the workforce tenant"
}

variable "oidc_jwks_uri" {
  type        = string
  default     = ""
  description = "Signing keys override; empty derives the workforce tenant"
}

variable "entra_authority_host" {
  type    = string
  default = "login.microsoftonline.com"
}

# --- edge ------------------------------------------------------------------------------------

variable "front_door_sku" {
  type        = string
  default     = "Standard_AzureFrontDoor"
  description = "Premium_AzureFrontDoor adds the managed WAF rule sets; Standard keeps a custom rate-limit rule only"
  validation {
    condition     = contains(["Standard_AzureFrontDoor", "Premium_AzureFrontDoor"], var.front_door_sku)
    error_message = "Standard_AzureFrontDoor or Premium_AzureFrontDoor."
  }
}

variable "waf_mode" {
  type    = string
  default = "Prevention"
  validation {
    condition     = contains(["Prevention", "Detection"], var.waf_mode)
    error_message = "Prevention or Detection."
  }
}

variable "waf_rate_limit_per_minute" {
  type        = number
  default     = 300
  description = "Requests per minute per client IP before Front Door blocks (AWS: 1000 per 5 minutes)"
}

variable "upload_limit_bytes" {
  type        = number
  default     = 20971520
  description = "No Lambda payload cap on Azure: the API's own 20 MB limit (ADR-016) applies"
}

# --- data ------------------------------------------------------------------------------------

variable "postgres_sku_name" {
  type    = string
  default = "B_Standard_B1ms"
}

variable "postgres_version" {
  type    = string
  default = "16"
}

variable "postgres_storage_mb" {
  type    = number
  default = 32768
}

variable "postgres_high_availability" {
  type        = bool
  default     = false
  description = "Zone-redundant standby (needs a General Purpose or Memory Optimized SKU)"
}

variable "postgres_max_connections" {
  type        = number
  default     = null
  nullable    = true
  description = "Connection ceiling the plan-time bulkhead check assumes; null uses a conservative value for the SKU"
}

variable "db_pool_size" {
  type    = number
  default = 3
}

variable "db_max_overflow" {
  type    = number
  default = 1
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "geo_redundant_backup" {
  type    = bool
  default = false
}

variable "storage_replication" {
  type    = string
  default = "LRS"
  validation {
    condition     = contains(["LRS", "ZRS", "GRS", "GZRS"], var.storage_replication)
    error_message = "LRS, ZRS, GRS or GZRS."
  }
}

variable "deletion_protection" {
  type        = bool
  default     = false
  description = "CanNotDelete locks on the database and the document store; remove them deliberately before destroying the pilot"
}

variable "servicebus_sku" {
  type        = string
  default     = "Standard"
  description = "Premium adds private endpoints (pilot); Standard is reachable over TLS with Entra authentication only"
  validation {
    condition     = contains(["Standard", "Premium"], var.servicebus_sku)
    error_message = "Standard or Premium."
  }
}

variable "web_pubsub_sku" {
  type    = string
  default = "Free_F1"
  validation {
    condition     = contains(["Free_F1", "Standard_S1"], var.web_pubsub_sku)
    error_message = "Free_F1 (20 connections) or Standard_S1."
  }
}

variable "defender_malware_scanning" {
  type        = bool
  default     = true
  description = "Defender for Storage on-upload malware scanning of the document store (ADR-022); billed per GB scanned"
}

variable "malware_scan_cap_gb_per_month" {
  type    = number
  default = 100
}

# --- models ----------------------------------------------------------------------------------

variable "llm_mode" {
  type    = string
  default = "azure_openai"
  validation {
    condition     = contains(["azure_openai", "none"], var.llm_mode)
    error_message = "azure_openai or none (extractive answers only)."
  }
}

variable "router_mode" {
  type    = string
  default = "hybrid"
  validation {
    condition     = contains(["baseline", "bedrock", "hybrid", "rizzo_flow"], var.router_mode)
    error_message = "baseline, bedrock (the semantic router, backed by the configured model), hybrid or rizzo_flow."
  }
}

variable "chat_model" {
  type = object({ name = string, version = string, sku = string, capacity = number })
  default = {
    name     = "gpt-4.1-mini"
    version  = "2025-04-14"
    sku      = "DataZoneStandard" # EU data zone: inference stays in the EU, like the eu.* Bedrock profile (ADR-002)
    capacity = 30                 # thousands of tokens per minute
  }
  validation {
    condition     = !contains(["GlobalStandard", "GlobalBatch", "GlobalProvisionedManaged"], var.chat_model.sku)
    error_message = "Global deployments may process data outside the EU: use Standard, DataZoneStandard or a provisioned SKU."
  }
}

variable "embedding_model" {
  type = object({ name = string, version = string, sku = string, capacity = number })
  default = {
    name     = "text-embedding-3-large"
    version  = "1"
    sku      = "DataZoneStandard"
    capacity = 30
  }
  validation {
    condition     = !contains(["GlobalStandard", "GlobalBatch", "GlobalProvisionedManaged"], var.embedding_model.sku)
    error_message = "Global deployments may process data outside the EU: use Standard, DataZoneStandard or a provisioned SKU."
  }
}

variable "content_safety_groundedness" {
  type        = bool
  default     = false
  description = "Groundedness detection on answers (preview API, offered in a few regions only): check availability before enabling"
}

# --- compute ---------------------------------------------------------------------------------

variable "acr_sku" {
  type    = string
  default = "Standard"
}

variable "zone_redundant" {
  type        = bool
  default     = false
  description = "Spread the Container Apps environment over the availability zones (pilot)"
}

variable "api_min_replicas" {
  type    = number
  default = 0 # scale to zero: the demo's first request pays a cold start
}

variable "gateway_min_replicas" {
  type    = number
  default = 0
}

variable "worker_min_replicas" {
  type    = number
  default = 0
}

variable "web_min_replicas" {
  type    = number
  default = 0
}

variable "max_replicas" {
  type = object({ api = number, jobs = number, agents = number, notifier = number, gateway = number, executor = number, web = number })
  default = {
    api      = 2 # the connection bulkhead of ADR-006: replicas x pool must fit the database (see the precondition in data.tf)
    jobs     = 2
    agents   = 2
    notifier = 1
    gateway  = 2
    executor = 2
    web      = 2
  }
}

variable "requeue_cron" {
  type        = string
  default     = "0 * * * *"
  description = "Recovery of lost messages, expired leases and undispatched agent runs (UTC cron); the pilot uses */2 * * * *"
}

variable "log_retention_days" {
  type    = number
  default = 30 # ADR-014
}

variable "notification_sender_username" {
  type    = string
  default = "DoNotReply"
}
