"""Tool allow-list, input contracts and distributed rate limits."""

import time
from collections import defaultdict
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PolicyDenied(Exception):
    pass


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500)
    space_ids: list[str] | None = Field(default=None, max_length=20)
    language: Literal["en", "da", "pl", "it"] | None = None
    territory: str | None = Field(default=None, max_length=20)
    top_k: int = Field(default=6, ge=1, le=10)


class KnowledgeAnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1000)
    space_ids: list[str] | None = Field(default=None, max_length=20)
    language: Literal["en", "da", "pl", "it"] | None = None
    territory: str | None = Field(default=None, max_length=20)


TOOLS = {
    "knowledge_search": {
        "description": "Hybrid RAG search over knowledge visible to the caller.",
        "input_model": KnowledgeSearchInput,
        "agents": frozenset({
            "donation_operations", "logistics_planning", "knowledge_research", "compliance_review", "mcp_client",
        }),
        "roles": frozenset({"coordinator", "org_admin", "volunteer", "center_staff", "platform_admin"}),
        "limit": 30,
    },
    "knowledge_answer": {
        "description": "Grounded RAG answer with citations and explicit abstention.",
        "input_model": KnowledgeAnswerInput,
        "agents": frozenset({"mcp_client"}),
        "roles": frozenset({"coordinator", "org_admin", "volunteer", "center_staff", "platform_admin"}),
        "limit": 10,
    },
}


class ToolPolicy:
    def authorize(self, name: str, agent: str, role: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = TOOLS.get(name)
        if spec is None:
            raise PolicyDenied("unknown tool")
        if agent not in spec["agents"]:
            raise PolicyDenied("agent is not allowed to call this tool")
        if role not in spec["roles"]:
            raise PolicyDenied("role is not allowed to call this tool")
        return spec["input_model"].model_validate(arguments).model_dump(mode="json", exclude_none=True)

    def catalog(self) -> list[dict[str, Any]]:
        return [{
            "name": name, "description": spec["description"],
            "input_schema": spec["input_model"].model_json_schema(),
            "agents": sorted(spec["agents"]), "roles": sorted(spec["roles"]),
            "read_only": True, "rate_limit_per_minute": spec["limit"],
        } for name, spec in TOOLS.items()]


class MemoryRateLimiter:
    """Local-only fixed-window limiter; AWS deployments use DynamoDBRateLimiter."""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._counts: dict[tuple[str, int], int] = defaultdict(int)
        self._lock = Lock()

    def consume(self, key: str, limit: int | None = None) -> None:
        window = int(time.time()) // self.window_seconds
        with self._lock:
            bucket = (key, window)
            self._counts[bucket] += 1
            if self._counts[bucket] > (limit or self.limit):
                raise PolicyDenied("rate limit exceeded")


class DynamoDBRateLimiter:
    def __init__(self, table_name: str, client=None) -> None:
        import boto3

        self.table_name = table_name
        self.client = client or boto3.client("dynamodb")

    def consume(self, key: str, limit: int) -> None:
        now = int(time.time())
        window = now // 60
        try:
            self.client.update_item(
                TableName=self.table_name,
                Key={"bucket": {"S": f"{key}:{window}"}},
                UpdateExpression="ADD requests :one SET expires_at = :expires",
                ConditionExpression="attribute_not_exists(requests) OR requests < :limit",
                ExpressionAttributeValues={
                    ":one": {"N": "1"}, ":limit": {"N": str(limit)}, ":expires": {"N": str(now + 120)},
                },
            )
        except self.client.exceptions.ConditionalCheckFailedException as exc:
            raise PolicyDenied("rate limit exceeded") from exc
