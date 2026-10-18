"""Allow-listed tool gateway. Models select tools; this module authorises and executes them."""

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session


class ToolDenied(Exception):
    pass


@dataclass(frozen=True)
class ToolContext:
    session: Session
    tenant_id: uuid.UUID
    subject: str
    role: str
    agent: str
    correlation_id: str


ToolHandler = Callable[[ToolContext, BaseModel], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    roles: frozenset[str]
    agents: frozenset[str]
    resource: str
    timeout_ms: int
    handler: ToolHandler
    read_only: bool = True


class ToolGateway:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        if not spec.read_only:
            raise ValueError("write tools require the proposal/approval executor")
        self._tools[spec.name] = spec

    def manifest(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_model.model_json_schema(),
                "roles": sorted(spec.roles),
                "agents": sorted(spec.agents),
                "resource": spec.resource,
                "timeout_ms": spec.timeout_ms,
                "read_only": spec.read_only,
            }
            for spec in self._tools.values()
        ]

    def call(self, name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolDenied("unknown tool")
        if context.role not in spec.roles:
            self._audit(context, name, "denied", {"reason": "role"})
            raise ToolDenied("role is not allowed to call this tool")
        if context.agent not in spec.agents:
            self._audit(context, name, "denied", {"reason": "agent"})
            raise ToolDenied("agent is not allowed to call this tool")
        body = spec.input_model.model_validate(arguments)
        fingerprint = hashlib.sha256(
            json.dumps(arguments, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()
        started = time.monotonic()
        try:
            # SET cannot take bind parameters (psycopg binds server-side): set_config(..., true) is SET LOCAL.
            context.session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"), {"timeout": str(spec.timeout_ms)}
            )
            result = spec.handler(context, body)
        except Exception:
            self._audit(context, name, "failed", {"input_sha256": fingerprint})
            raise
        self._audit(
            context,
            name,
            "success",
            {"input_sha256": fingerprint, "latency_ms": int((time.monotonic() - started) * 1000)},
        )
        return result

    @staticmethod
    def _audit(context: ToolContext, name: str, outcome: str, details: dict[str, Any]) -> None:
        context.session.execute(
            text(
                "INSERT INTO audit_event"
                " (actor, actor_role, action, object_type, outcome, correlation_id, details)"
                " VALUES (:actor, :role, :action, 'tool', :outcome, :cid, CAST(:details AS jsonb))"
            ),
            {
                "actor": context.subject,
                "role": context.role,
                "action": f"tool.{name}",
                "outcome": outcome,
                "cid": context.correlation_id,
                "details": json.dumps({"agent": context.agent, **details}),
            },
        )
