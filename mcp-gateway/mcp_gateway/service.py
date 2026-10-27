"""Gateway orchestration. No application or database package is imported here."""

import json
import logging
import os
import time
from functools import lru_cache
from typing import Any

import boto3

from mcp_gateway.policy import MemoryRateLimiter, PolicyDenied, TOOLS, ToolPolicy

log = logging.getLogger(__name__)
# Bare JSON lines: awslambdaric's default handler prefixes level, time and request id, and the
# CloudWatch metric filter on {$.event = "tool_call"} matches only lines that are pure JSON.
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().handlers = [_handler]
logging.getLogger().setLevel(os.getenv("SECONDCHANCE_LOG_LEVEL", "INFO"))
policy = ToolPolicy()
limiter = MemoryRateLimiter(30)


@lru_cache
def _table_limiter():
    from mcp_gateway.policy import TableRateLimiter

    return TableRateLimiter()


def _rate_limiter():
    if os.getenv("SECONDCHANCE_MCP_RATE_LIMIT_TABLE_ENDPOINT"):  # Azure Table Storage
        return _table_limiter()
    table = os.getenv("SECONDCHANCE_MCP_RATE_LIMIT_TABLE")
    if table:
        from mcp_gateway.policy import DynamoDBRateLimiter

        return DynamoDBRateLimiter(table)
    return limiter


def handle(payload: dict[str, Any], executor=None) -> dict[str, Any]:
    started = time.monotonic()
    context = payload.get("context", {})
    name = payload.get("name", "")
    try:
        arguments = policy.authorize(name, context.get("agent", ""), context.get("role", ""), payload.get("arguments", {}))
        key = f"{context.get('tenant_id')}:{context.get('subject')}:{name}"
        _rate_limiter().consume(key, TOOLS[name]["limit"])
        invoke = executor or _invoke_executor
        result = invoke({"name": name, "arguments": arguments, "context": context})
        log.info(json.dumps({"event": "tool_call", "tool": name, "outcome": "success",
                            "correlation_id": context.get("correlation_id"),
                            "latency_ms": int((time.monotonic() - started) * 1000)}))
        return {"result": result}
    except PolicyDenied as exc:
        log.warning(json.dumps({"event": "tool_call", "tool": name, "outcome": "denied",
                               "reason": str(exc), "correlation_id": context.get("correlation_id")}))
        return {"error": str(exc), "status_code": 429 if "rate limit" in str(exc) else 403}
    except Exception:
        log.exception(json.dumps({"event": "tool_call", "tool": name, "outcome": "failed",
                                  "correlation_id": context.get("correlation_id")}))
        raise


def _invoke_executor(payload: dict[str, Any]) -> dict[str, Any]:
    executor_url = os.getenv("SECONDCHANCE_TOOL_EXECUTOR_URL")
    if executor_url:
        import httpx

        headers = {}
        executor_client_id = os.getenv("SECONDCHANCE_TOOL_EXECUTOR_AUDIENCE")
        if executor_client_id:  # Azure: the gateway proves its identity to the executor (ADR-023)
            from mcp_gateway.service_auth import token_for

            headers["Authorization"] = f"Bearer {token_for(executor_client_id)}"
        response = httpx.post(f"{executor_url.rstrip('/')}/execute", json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    function_name = os.environ["SECONDCHANCE_TOOL_EXECUTOR_FUNCTION"]
    response = boto3.client("lambda").invoke(
        FunctionName=function_name, InvocationType="RequestResponse",
        Payload=json.dumps(payload, separators=(",", ":")).encode(),
    )
    body = json.loads(response["Payload"].read())
    if response.get("FunctionError") or "errorMessage" in body:
        raise RuntimeError(body.get("errorMessage", "tool executor failed"))
    return body
