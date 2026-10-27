"""Client for the independently deployed MCP Tool Gateway."""

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import boto3
import httpx


@dataclass(frozen=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any]
    tenant_id: str
    subject: str
    role: str
    agent: str
    correlation_id: str
    run_id: str | None = None
    seq: int | None = None

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        return {"name": value.pop("name"), "arguments": value.pop("arguments"), "context": value}


class ToolGatewayClient:
    def __init__(
        self,
        *,
        function_name: str | None = None,
        base_url: str | None = None,
        lambda_client=None,
    ) -> None:
        self.function_name = function_name
        self.base_url = base_url
        self.lambda_client = lambda_client

    @classmethod
    def from_environment(cls) -> "ToolGatewayClient":
        function_name = os.getenv("SECONDCHANCE_MCP_GATEWAY_FUNCTION")
        base_url = os.getenv("SECONDCHANCE_MCP_GATEWAY_URL")
        if not function_name and not base_url:
            raise RuntimeError("MCP Tool Gateway is not configured")
        return cls(function_name=function_name, base_url=base_url)

    def call(self, invocation: ToolInvocation) -> dict[str, Any]:
        payload = invocation.payload()
        if self.function_name:
            client = self.lambda_client or boto3.client("lambda")
            response = client.invoke(
                FunctionName=self.function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload, separators=(",", ":")).encode(),
            )
            body = json.loads(response["Payload"].read())
            if response.get("FunctionError") or "error" in body or "errorMessage" in body:
                raise RuntimeError(body.get("error") or body.get("errorMessage") or "MCP gateway failed")
            return body["result"]
        if not self.base_url:
            raise RuntimeError("MCP Tool Gateway is not configured")
        headers = {}
        gateway_client_id = os.getenv("SECONDCHANCE_MCP_GATEWAY_AUDIENCE")
        if gateway_client_id:  # Azure: the caller proves who it is with its managed identity (ADR-023)
            from secondchance.service_auth import token_for

            headers["Authorization"] = f"Bearer {token_for(gateway_client_id)}"
        response = httpx.post(f"{self.base_url.rstrip('/')}/v1/tools/call", json=payload, headers=headers, timeout=35)
        response.raise_for_status()
        return response.json()["result"]
