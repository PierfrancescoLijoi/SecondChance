"""Model adapter (FR-035, ADR-015): Claude on Amazon Bedrock, Azure OpenAI, Ollama locally, or none.

With no model configured the knowledge service still answers, extractively, from the
retrieved sections. Prompts are versioned files; their hash is recorded (ADR-008).
On AWS, Bedrock Guardrails run as a separate ApplyGuardrail check on the question
(prompt attacks, PII) and on the answer (contextual grounding against the sources). On Azure the same
two checks come from Azure AI Content Safety (Prompt Shields and harm categories on the question,
harm categories and, where the region offers it, groundedness on the answer; ADR-023).
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


COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
# Reasoning models accept neither a temperature nor the legacy token parameter.
_FIXED_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def azure_openai_client(endpoint: str):
    """OpenAI SDK on the Azure v1 route, authenticated with a managed-identity token (no API key)."""
    from openai import OpenAI

    from secondchance.cloud import azure_credential

    def token() -> str:
        return azure_credential().get_token(COGNITIVE_SCOPE).token

    return OpenAI(base_url=f"{endpoint.rstrip('/')}/openai/v1/", api_key=token, max_retries=3, timeout=60)


class AzureOpenAIModel:
    """A chat deployment on Azure OpenAI. Errors surface as ConnectionError so callers that already
    degrade on an unreachable model (the semantic router) do so here too."""

    def __init__(self, endpoint: str, deployment: str, client=None) -> None:
        self.client = client or azure_openai_client(endpoint)
        self.model_id = deployment

    def complete(self, system: str, user: str) -> Completion:
        import openai

        options: dict = {"max_completion_tokens": 8000}
        if not self.model_id.startswith(_FIXED_TEMPERATURE_PREFIXES):
            options["temperature"] = 0.1
        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **options,
            )
        except openai.BadRequestError as error:
            if getattr(error, "code", None) == "content_filter":  # the deployment's RAI policy blocked the prompt
                return Completion("", 0, 0, refused=True)
            raise ConnectionError(f"Azure OpenAI rejected the request: {error}") from error
        except openai.OpenAIError as error:
            raise ConnectionError(f"Azure OpenAI is unavailable: {error}") from error
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            return Completion("", input_tokens, output_tokens, refused=True)
        return Completion(choice.message.content or "", input_tokens, output_tokens)


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


class AzureContentSafetyGuardrail:
    """Azure AI Content Safety as the guardrail (ADR-015, ADR-023): independent of the model, like ApplyGuardrail.

    The question is checked for prompt attacks and harm; the answer for harm and, when
    SECONDCHANCE_GROUNDEDNESS=1 (a preview API, offered in a few regions only), for claims the sources
    do not support. A service error raises: the caller must not publish an answer nobody checked.
    """

    API_VERSION = "2024-09-01"
    GROUNDEDNESS_API_VERSION = "2024-09-15-preview"
    CATEGORIES = ["Hate", "SelfHarm", "Sexual", "Violence"]
    MAX_CHARS = 10000

    def __init__(self, endpoint: str, *, severity_threshold: int = 4, groundedness: bool = False, http=None) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.severity_threshold = severity_threshold  # FourSeverityLevels: 0, 2, 4 (medium), 6
        self.groundedness = groundedness
        self.http = http

    def _post(self, path: str, body: dict, api_version: str) -> dict:
        import httpx

        from secondchance.cloud import bearer

        try:
            response = (self.http or httpx).post(
                f"{self.endpoint}/contentsafety/{path}", params={"api-version": api_version}, json=body,
                headers={"Authorization": f"Bearer {bearer(COGNITIVE_SCOPE)}"}, timeout=15,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ConnectionError(f"Azure AI Content Safety is unavailable: {error}") from error
        return response.json()

    def _harmful(self, text: str) -> bool:
        result = self._post(
            "text:analyze",
            {"text": text[: self.MAX_CHARS], "categories": self.CATEGORIES, "outputType": "FourSeverityLevels"},
            self.API_VERSION,
        )
        return any(item.get("severity", 0) >= self.severity_threshold for item in result.get("categoriesAnalysis", []))

    def blocks_question(self, question: str) -> bool:
        shield = self._post(
            "text:shieldPrompt", {"userPrompt": question[: self.MAX_CHARS], "documents": []}, self.API_VERSION
        )
        if shield.get("userPromptAnalysis", {}).get("attackDetected"):
            return True
        return self._harmful(question)

    def blocks_answer(self, question: str, sources: list[str], answer: str) -> bool:
        if self._harmful(answer):
            return True
        if not self.groundedness or not sources:
            return False
        result = self._post(
            "text:detectGroundedness",
            {
                "domain": "Generic", "task": "QnA", "qna": {"query": question[:2000]},
                "text": answer[: self.MAX_CHARS], "groundingSources": ["\n\n".join(sources)[:55000]],
                "reasoning": False,
            },
            self.GROUNDEDNESS_API_VERSION,
        )
        return bool(result.get("ungroundedDetected"))


@lru_cache
def model() -> Model | None:
    kind = os.environ.get("SECONDCHANCE_LLM", "none")
    if kind == "azure_openai":
        return AzureOpenAIModel(os.environ["SECONDCHANCE_AZURE_OPENAI_ENDPOINT"], os.environ["SECONDCHANCE_AZURE_OPENAI_CHAT_DEPLOYMENT"])
    if kind == "bedrock":
        # Model availability per region changes: verify before deploying (ADR-002).
        return BedrockClaude(os.environ.get("SECONDCHANCE_BEDROCK_MODEL", "eu.anthropic.claude-haiku-5-5"))
    if kind == "ollama":
        return OllamaModel(os.environ["SECONDCHANCE_OLLAMA_URL"], os.environ.get("SECONDCHANCE_OLLAMA_MODEL", "qwen3:4b"))
    return None


@lru_cache
def guardrail() -> Guardrail | AzureContentSafetyGuardrail | None:
    endpoint = os.environ.get("SECONDCHANCE_CONTENT_SAFETY_ENDPOINT")
    if endpoint:
        return AzureContentSafetyGuardrail(endpoint, groundedness=os.environ.get("SECONDCHANCE_GROUNDEDNESS") == "1")
    identifier = os.environ.get("SECONDCHANCE_GUARDRAIL_ID")
    return Guardrail(identifier, os.environ.get("SECONDCHANCE_GUARDRAIL_VERSION", "DRAFT")) if identifier else None


@lru_cache
def prompt(name: str) -> tuple[str, str]:
    """(template, sha256): the hash identifies the prompt version in step metadata."""
    template = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    return template, hashlib.sha256(template.encode()).hexdigest()
