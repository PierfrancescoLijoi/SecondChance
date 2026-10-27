import os
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.admission import admit_agent_run
from secondchance.agents.builtin import CATALOG
from secondchance.agents.dispatch import configured_dispatcher
from secondchance.agents.runtime import start_run
from secondchance.db import tenant_transaction
from secondchance.identity import Claims, current_claims, require_roles, tenant_session
from secondchance.memory import recall
from secondchance.observability import current_correlation_id
from secondchance.queues import Queue
from secondchance.realtime import azure_client_url

router = APIRouter(tags=["agents"])
TenantSession = Depends(tenant_session, scope="function")


@lru_cache
def agents_queue() -> Queue:
    return configured_dispatcher()


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=3, max_length=2000)


class AgentRunCreated(BaseModel):
    id: uuid.UUID
    status: Literal["queued"]


class AgentStep(BaseModel):
    seq: int
    agent: str
    status: str
    model_id: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int | None
    error_category: str | None


class AgentRun(BaseModel):
    id: uuid.UUID
    status: str
    steps_used: int
    max_steps: int
    tokens_used: int
    max_tokens: int
    deadline_at: datetime
    created_at: datetime
    steps: list[AgentStep]
    findings: list[str]
    # AI Act art. 50: whatever an agent wrote is labelled as generated.
    generated_by: Literal["secondchance-agents"] = "secondchance-agents"


@router.get("/agents/catalog")
def get_agent_catalog(_: Claims = Depends(require_roles("coordinator", "org_admin"))) -> list[dict[str, object]]:
    """Expose the deployed governance contract; never includes prompts or credentials."""
    return CATALOG.manifest()


def start_agent_run(claims: Claims, task: str, queue: Queue) -> uuid.UUID:
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        admit_agent_run(session)  # ADR-016: quota before any work is created
        run_id, message = start_run(session, claims, task, current_correlation_id())
    # After the commit: if this send fails, the requeue job re-sends the pending step.
    queue.send(message)
    return run_id


@router.post("/agent-runs", response_model=AgentRunCreated, status_code=202)
def post_agent_run(
    body: AgentRunRequest,
    claims: Claims = Depends(require_roles("coordinator", "org_admin")),
    queue: Queue = Depends(agents_queue),
) -> AgentRunCreated:
    return AgentRunCreated(id=start_agent_run(claims, body.task, queue), status="queued")


class RealtimeConnection(BaseModel):
    url: str
    expires_in: int


@router.get("/agent-runs/{run_id}/realtime", response_model=RealtimeConnection)
def get_agent_run_realtime(run_id: uuid.UUID, claims: Claims = Depends(current_claims), session: Session = TenantSession) -> RealtimeConnection:
    """Azure: a Web PubSub URL for this run, minted after the same membership and ownership checks the
    AWS WebSocket connect route makes. 404 hides runs that are not the caller's; 503 means polling only."""
    if not os.environ.get("SECONDCHANCE_WEBPUBSUB_ENDPOINT"):
        raise HTTPException(503, "real-time updates are not configured")
    owner = session.execute(text("SELECT requested_by FROM agent_run WHERE id = :id"), {"id": run_id}).scalar_one_or_none()
    if owner is None or owner != claims.sub:
        raise HTTPException(404, "run not found")
    minutes = 60
    return RealtimeConnection(url=azure_client_url(claims.sub, run_id, minutes=minutes), expires_in=minutes * 60)


@router.get("/agent-runs/{run_id}", response_model=AgentRun)
def get_agent_run(run_id: uuid.UUID, session: Session = TenantSession) -> AgentRun:
    run = session.execute(
        text(
            "SELECT id, status, steps_used, max_steps, tokens_used, max_tokens, deadline_at, created_at"
            " FROM agent_run WHERE id = :id"
        ),
        {"id": run_id},
    ).mappings().one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    steps = session.execute(
        text(
            "SELECT seq, agent, status, model_id, input_tokens, output_tokens, latency_ms, error_category"
            " FROM agent_step WHERE run_id = :id ORDER BY seq"
        ),
        {"id": run_id},
    ).mappings()
    findings = recall(session, scope="run", run_id=run_id, kinds=("finding",))
    return AgentRun(**run, steps=[AgentStep(**s) for s in steps], findings=[f.content for f in reversed(findings)])
