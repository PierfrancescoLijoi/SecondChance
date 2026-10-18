# Bedrock Guardrails applied with ApplyGuardrail around every generated answer (ADR-015):
# prompt attacks blocked on input, contact data masked, answers checked against the sources.

resource "aws_bedrock_guardrail" "main" {
  name                      = var.name
  description               = "SecondChance knowledge answers"
  blocked_input_messaging   = "Richiesta non consentita."
  blocked_outputs_messaging = "Risposta non disponibile: verifica con un referente."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "HATE"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
  }

  sensitive_information_policy_config {
    dynamic "pii_entities_config" {
      for_each = ["EMAIL", "PHONE", "NAME", "ADDRESS", "INTERNATIONAL_BANK_ACCOUNT_NUMBER"]
      content {
        type   = pii_entities_config.value
        action = "ANONYMIZE"
      }
    }
  }

  contextual_grounding_policy_config {
    filters_config {
      type      = "GROUNDING"
      threshold = 0.75
    }
    filters_config {
      type      = "RELEVANCE"
      threshold = 0.5
    }
  }
}

resource "aws_bedrock_guardrail_version" "main" {
  guardrail_arn = aws_bedrock_guardrail.main.guardrail_arn
  description   = "deployed ${var.image_tag}"
}
