"""Model adapter (FR-035, ADR-015): Claude on Amazon Bedrock, Ollama locally, or none.

With no model configured the knowledge service still answers, extractively, from the
retrieved sections. Prompts are versioned files; their hash is recorded (ADR-008).
On AWS, Bedrock Guardrails run as a separate ApplyGuardrail check on the question
(prompt attacks, PII) and on the answer (contextual grounding against the sources).
"""

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

PROMPTS = Path(__file__).parent / "prompts"
REGION = os.environ.get("AWS_REGION", "eu-central-1")


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    refused: bool = False


class Model(Protocol):
    model_id: str

    def complete(self, system: str, user: str) -> Completion: ...


class BedrockClaude:
    """Claude through Bedrock Runtime Converse; credentials come from the Lambda role.

    The application Lambdas run in private subnets without NAT. Using boto3's regional
    Bedrock Runtime client keeps traffic on the configured ``bedrock-runtime`` VPC
    endpoint; the separate Bedrock Mantle endpoint is intentionally not required.
    """

    def __init__(self, model_id: str) -> None:
        import boto3

        self.client = boto3.client("bedrock-runtime", region_name=REGION)
        self.model_id = model_id

    def complete(self, system: str, user: str) -> Completion:
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": 8000, "temperature": 0.1},
        )
        usage = response.get("usage", {})
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        if response.get("stopReason") in {"content_filtered", "guardrail_intervened"}:
            return Completion("", input_tokens, output_tokens, refused=True)
        content = response.get("output", {}).get("message", {}).get("content", [])
        text = "".join(block.get("text", "") for block in content if "text" in block)
        return Completion(text, input_tokens, output_tokens)


class OllamaModel:
    def __init__(self, base_url: str, model_id: str) -> None:
        self.url = base_url.rstrip("/") + "/api/chat"
        self.model_id = model_id

    def complete(self, system: str, user: str) -> Completion:
        body = {
            "model": self.model_id, "stream": False, "options": {"temperature": 0.1},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        return Completion(payload["message"]["content"], payload.get("prompt_eval_count", 0), payload.get("eval_count", 0))


class Guardrail:
    """Bedrock ApplyGuardrail: usable with any model, so the policy stays independent of it."""

    def __init__(self, identifier: str, version: str) -> None:
        import boto3

        self.client = boto3.client("bedrock-runtime", region_name=REGION)
        self.identifier, self.version = identifier, version

    def _intervened(self, source: str, content: list[dict]) -> bool:
        result = self.client.apply_guardrail(
            guardrailIdentifier=self.identifier, guardrailVersion=self.version, source=source, content=content
        )
        return result["action"] == "GUARDRAIL_INTERVENED"

    def blocks_question(self, question: str) -> bool:
        return self._intervened("INPUT", [{"text": {"text": question}}])

    def blocks_answer(self, question: str, sources: list[str], answer: str) -> bool:
        content = [{"text": {"text": s, "qualifiers": ["grounding_source"]}} for s in sources]
        content += [{"text": {"text": question, "qualifiers": ["query"]}},
                    {"text": {"text": answer, "qualifiers": ["guard_content"]}}]
        return self._intervened("OUTPUT", content)


@lru_cache
def model() -> Model | None:
    kind = os.environ.get("SECONDCHANCE_LLM", "none")
    if kind == "bedrock":
        # Model availability per region changes: verify before deploying (ADR-002).
        return BedrockClaude(os.environ.get("SECONDCHANCE_BEDROCK_MODEL", "eu.anthropic.claude-haiku-5-5"))
    if kind == "ollama":
        return OllamaModel(os.environ["SECONDCHANCE_OLLAMA_URL"], os.environ.get("SECONDCHANCE_OLLAMA_MODEL", "qwen3:4b"))
    return None


@lru_cache
def guardrail() -> Guardrail | None:
    identifier = os.environ.get("SECONDCHANCE_GUARDRAIL_ID")
    return Guardrail(identifier, os.environ.get("SECONDCHANCE_GUARDRAIL_VERSION", "DRAFT")) if identifier else None


@lru_cache
def prompt(name: str) -> tuple[str, str]:
    """(template, sha256): the hash identifies the prompt version in step metadata."""
    template = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    return template, hashlib.sha256(template.encode()).hexdigest()
