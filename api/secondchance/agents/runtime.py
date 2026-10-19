"""Durable, stateless agent execution (ADR-010).

A run is a chain of steps stored in Postgres. Any worker can execute any step:
1. claim   - short transaction: take the step with a lease, check the run's budgets;
2. execute - no transaction held: the agent reads what it needs and may call a model;
3. complete - short transaction, fenced by the claim's attempt number: record the step,
   write the agent's memories, update the run, insert the next step.
The next message is sent only after the commit, so SQS at-least-once delivery is safe:
a redelivered message finds the step already done, a crashed worker's lease expires.
"""

import logging
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from secondchance.db import tenant_transaction
from secondchance.memory import Kind, remember
from secondchance.observability import meter
from secondchance.principal import Claims
from secondchance.queues import Queue

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)  # keep below the queue's visibility timeout
STALE_PENDING = timedelta(minutes=2)  # a pending step older than this lost its message
WORKER_ROLE = "agent_worker"
TERMINAL = ("succeeded", "failed", "budget_exhausted", "cancelled", "waiting_approval")

steps_counter = meter.create_counter("secondchance.agent.steps", description="Agent steps by agent and outcome")
tokens_counter = meter.create_counter("secondchance.agent.tokens", description="Model tokens by agent and direction")


@dataclass(frozen=True)
class RunContext:
    run_id: uuid.UUID
    tenant_id: uuid.UUID
    subject: str
    role: str
    seq: int
    agent: str
    correlation_id: str

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Short tenant transaction with the run's identity; never one chosen by a model."""
        with tenant_transaction(self.tenant_id, self.role) as session:
            yield session


@dataclass(frozen=True)
class StepResult:
    outcome: Literal["continue", "succeeded", "failed", "waiting_approval"]
    next_agent: str | None = None
    memories: tuple[tuple[Kind, str], ...] = field(default_factory=tuple)
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str | None = None
    prompt_sha256: str | None = None
    error_category: str | None = None


Agent = Callable[[RunContext], StepResult]


def start_run(
    session: Session, claims: Claims, task: str, correlation_id: str, max_steps: int = 12
) -> tuple[uuid.UUID, dict]:
    """Creates the run, its task memory and the first step. Send the message after commit."""
    run_id = session.execute(
        text(
            "INSERT INTO agent_run (requested_by, requested_role, max_steps, correlation_id)"
            " VALUES (:sub, :role, :max_steps, :cid) RETURNING id"
        ),
        {"sub": claims.sub, "role": claims.role, "max_steps": max_steps, "cid": correlation_id},
    ).scalar_one()
    remember(session, scope="run", run_id=run_id, kind="task", content=task, source="operator")
    session.execute(
        text("INSERT INTO agent_step (run_id, seq, agent) VALUES (:run, 1, 'supervisor')"), {"run": run_id}
    )
    return run_id, step_message(claims.tenant_id, run_id, 1, correlation_id)


def step_message(tenant_id: uuid.UUID, run_id: uuid.UUID, seq: int, correlation_id: str) -> dict:
    return {"tenant_id": str(tenant_id), "run_id": str(run_id), "seq": seq, "correlation_id": correlation_id}


def _claim(tenant_id: uuid.UUID, run_id: uuid.UUID, seq: int) -> tuple[RunContext, int, int] | str:
    with tenant_transaction(tenant_id, WORKER_ROLE) as session:
        run = session.execute(
            text(
                "SELECT status, requested_by, requested_role, correlation_id, version,"
                " steps_used >= max_steps OR tokens_used >= max_tokens OR deadline_at < now() AS over_budget"
                " FROM agent_run WHERE id = :run FOR UPDATE"
            ),
            {"run": run_id},
        ).mappings().one_or_none()
        if run is None:
            return "missing"  # deleted, or another tenant's id: RLS hides it
        if run["status"] in TERMINAL:
            return "run_closed"
        if run["over_budget"]:
            session.execute(
                text(
                    "UPDATE agent_step SET status = 'failed', error_category = 'budget', finished_at = now()"
                    " WHERE run_id = :run AND seq = :seq AND status IN ('pending', 'running')"
                ),
                {"run": run_id, "seq": seq},
            )
            session.execute(
                text(
                    "UPDATE agent_run SET status = 'budget_exhausted', version = version + 1, updated_at = now()"
                    " WHERE id = :run"
                ),
                {"run": run_id},
            )
            return "budget_exhausted"
        step = session.execute(
            text(
                "UPDATE agent_step SET status = 'running', attempt = attempt + 1, lease_until = now() + :lease"
                " WHERE run_id = :run AND seq = :seq"
                " AND (status = 'pending' OR (status = 'running' AND lease_until < now()))"
                " RETURNING agent, attempt"
            ),
            {"run": run_id, "seq": seq, "lease": LEASE},
        ).mappings().one_or_none()
        if step is None:
            return "not_claimable"  # done already, or leased by a live worker
        session.execute(
            text("UPDATE agent_run SET status = 'running', updated_at = now() WHERE id = :run AND status = 'queued'"),
            {"run": run_id},
        )
        context = RunContext(
            run_id=run_id,
            tenant_id=tenant_id,
            subject=run["requested_by"],
            role=run["requested_role"],
            seq=seq,
            agent=step["agent"],
            correlation_id=run["correlation_id"],
        )
        return context, step["attempt"], run["version"]


def _complete(context: RunContext, attempt: int, result: StepResult, latency_ms: int) -> str | bool:
    run_status = {"continue": "running", "succeeded": "succeeded", "failed": "failed",
                  "waiting_approval": "waiting_approval"}[result.outcome]
    with tenant_transaction(context.tenant_id, WORKER_ROLE) as session:
        fenced = session.execute(
            text(
                "UPDATE agent_step SET status = :status, model_id = :model, prompt_sha256 = :prompt,"
                " input_tokens = :tin, output_tokens = :tout, latency_ms = :latency,"
                " error_category = :error, finished_at = now(), lease_until = NULL"
                " WHERE run_id = :run AND seq = :seq AND attempt = :attempt AND status = 'running'"
            ),
            {
                "status": "failed" if result.outcome == "failed" else "succeeded",
                "model": result.model_id,
                "prompt": result.prompt_sha256,
                "tin": result.input_tokens,
                "tout": result.output_tokens,
                "latency": latency_ms,
                "error": result.error_category,
                "run": context.run_id,
                "seq": context.seq,
                "attempt": attempt,
            },
        ).rowcount
        if fenced == 0:
            session.rollback()
            return False  # lease expired and another worker took over: drop this result
        for kind, content in result.memories:
            remember(session, scope="run", run_id=context.run_id, kind=kind, content=content, source=context.agent)
        final_status = session.execute(
            text(
                "UPDATE agent_run SET status = CASE"
                " WHEN :status = 'running' AND (steps_used + 1 >= max_steps"
                " OR tokens_used + :tokens >= max_tokens OR deadline_at <= now())"
                " THEN 'budget_exhausted' ELSE :status END,"
                " steps_used = steps_used + 1, tokens_used = tokens_used + :tokens,"
                " version = version + 1, updated_at = now() WHERE id = :run RETURNING status"
            ),
            {"status": run_status, "tokens": result.input_tokens + result.output_tokens, "run": context.run_id},
        ).scalar_one()
        if result.outcome == "continue" and final_status == "running":
            session.execute(
                text(
                    "INSERT INTO agent_step (run_id, seq, agent) VALUES (:run, :seq, :agent)"
                    " ON CONFLICT (run_id, seq) DO NOTHING"
                ),
                {"run": context.run_id, "seq": context.seq + 1, "agent": result.next_agent},
            )
    return final_status


def execute(message: dict, agents: Mapping[str, Agent], queue: Queue, *, dispatch_next: bool = True) -> str:
    """Runs one step from a queue message. Returns what happened, for logs and tests."""
    tenant_id, run_id, seq = uuid.UUID(message["tenant_id"]), uuid.UUID(message["run_id"]), int(message["seq"])
    claimed = _claim(tenant_id, run_id, seq)
    if isinstance(claimed, str):
        return claimed
    context, attempt, _ = claimed

    started = time.monotonic()
    agent = agents.get(context.agent)
    if agent is None:
        result = StepResult(outcome="failed", error_category="unknown_agent")
    else:
        try:
            result = agent(context)
        except Exception:
            log.exception("agent %s failed on step %s", context.agent, context.seq)
            result = StepResult(outcome="failed", error_category="agent_exception")
    if result.outcome == "continue" and result.next_agent is None:
        result = StepResult(outcome="failed", error_category="missing_next_agent")

    final_status = _complete(context, attempt, result, int((time.monotonic() - started) * 1000))
    if not final_status:
        return "fenced"
    steps_counter.add(1, {"agent": context.agent, "outcome": result.outcome})
    tokens_counter.add(result.input_tokens, {"agent": context.agent, "direction": "input"})
    tokens_counter.add(result.output_tokens, {"agent": context.agent, "direction": "output"})
    outcome = "budget_exhausted" if final_status == "budget_exhausted" else result.outcome
    if outcome == "continue" and dispatch_next:
        queue.send(step_message(tenant_id, run_id, seq + 1, context.correlation_id))
    from secondchance.realtime import publish_run_event

    publish_run_event(str(run_id), {
        "type": "run.status", "run_id": str(run_id), "seq": seq, "outcome": outcome,
    })
    return outcome


def workflow_resume(tenant_id: uuid.UUID, run_id: uuid.UUID, seq: int) -> str:
    """Resolve a Step Functions retry from the state committed in Aurora.

    A Lambda response can be lost after its transaction committed. In that case the
    retried task must advance to the already-created next step. If the original lease
    is still live, the workflow waits instead of spinning or ending early.
    """
    with tenant_transaction(tenant_id, WORKER_ROLE) as session:
        row = session.execute(
            text(
                "SELECT r.status AS run_status, current.status AS current_status, next.status AS next_status"
                " FROM agent_run r"
                " LEFT JOIN agent_step current ON current.run_id = r.id AND current.seq = :seq"
                " LEFT JOIN agent_step next ON next.run_id = r.id AND next.seq = :next_seq"
                " WHERE r.id = :run"
            ),
            {"run": run_id, "seq": seq, "next_seq": seq + 1},
        ).mappings().one_or_none()
    if row is None or row["run_status"] in TERMINAL:
        return "complete"
    if row["next_status"] in {"pending", "running", "succeeded"}:
        return "advance"
    if row["current_status"] == "running":
        return "wait"
    return "complete"


def requeue_stale(connection: Connection, queue: Queue) -> int:
    """Re-sends steps nobody is working on: lost messages and expired leases.

    The API commits a run before sending its first message, so a failed send leaves a
    pending step behind; this job (every minute, as secondchance_maintenance) picks it up.
    Duplicate messages are harmless because claims are fenced.
    """
    rows = connection.execute(
        text(
            "SELECT s.tenant_id, s.run_id, s.seq, r.correlation_id FROM agent_step s"
            " JOIN agent_run r ON r.id = s.run_id"
            " WHERE (s.status = 'pending' AND s.created_at < now() - :stale)"
            " OR (s.status = 'running' AND s.lease_until < now())"
        ),
        {"stale": STALE_PENDING},
    ).all()
    for row in rows:
        queue.send(step_message(row.tenant_id, row.run_id, row.seq, row.correlation_id))
    return len(rows)
