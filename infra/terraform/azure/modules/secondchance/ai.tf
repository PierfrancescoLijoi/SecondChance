# Models and guardrails (ADR-015, ADR-023). One Azure AI Services account holds the chat and embedding
# deployments and the Content Safety API; data stays in the EU data zone (DataZoneStandard), the counterpart
# of the eu.* Bedrock inference profile. Key authentication is off; callers hold the "OpenAI User" and
# "Cognitive Services User" roles.
#
# Parity with the Bedrock guardrail: prompt attacks (Prompt Shields) and harm categories are checked by the
# application through Content Safety (secondchance.llm.AzureContentSafetyGuardrail); the deployments' default
# content filter (medium severity and above blocked in hate, sexual, violence and self-harm, on prompts and
# completions) is a second, model-side layer that needs no configuration. PII anonymisation and grounding checks are not
# reproduced by default (docs/deployment-azure.md, "What is not the same").

resource "azurerm_cognitive_account" "ai" {
  name                          = "ai-${var.name}-${local.suffix}"
  location                      = azurerm_resource_group.main.location
  resource_group_name           = azurerm_resource_group.main.name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "${var.name}-${local.suffix}"
  local_auth_enabled            = false
  public_network_access_enabled = false
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }
}

# Deployments are created one after the other: parallel writes to one account answer RequestConflict.
resource "azurerm_cognitive_deployment" "chat" {
  count                  = var.llm_mode == "azure_openai" ? 1 : 0
  name                   = "chat"
  cognitive_account_id   = azurerm_cognitive_account.ai.id
  version_upgrade_option = "NoAutoUpgrade" # a model change is a reviewed change (ADR-008)

  model {
    format  = "OpenAI"
    name    = var.chat_model.name
    version = var.chat_model.version
  }

  sku {
    name     = var.chat_model.sku
    capacity = var.chat_model.capacity
  }
}

resource "azurerm_cognitive_deployment" "embedding" {
  name                   = "embedding"
  cognitive_account_id   = azurerm_cognitive_account.ai.id
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = "OpenAI"
    name    = var.embedding_model.name
    version = var.embedding_model.version
  }

  sku {
    name     = var.embedding_model.sku
    capacity = var.embedding_model.capacity
  }

  depends_on = [azurerm_cognitive_deployment.chat]
}

locals {
  openai_endpoint         = "https://${azurerm_cognitive_account.ai.custom_subdomain_name}.openai.azure.com"
  content_safety_endpoint = "https://${azurerm_cognitive_account.ai.custom_subdomain_name}.cognitiveservices.azure.com"
}
