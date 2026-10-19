"""ADR-010: durable, stateless agent runs. At-least-once delivery never runs a step twice."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from secondchance.agents.builtin import AGENTS
from secondchance.agents.runtime import StepResult, _claim, _complete, execute, requeue_stale, start_run, workflow_resume
from secondchance.agents.worker import drain
from secondchance.identity import Claims
from secondchance.db import tenant_transaction
from secondchance.memory import recall
from secondchance.queues import MemoryQueue
from secondchance.seed import TENANT_DK, TENANT_IT
from secondchance.tools.client import ToolGatewayClient

IT_COORDINATOR = Claims(sub="coord-it", tenant_id=TENANT_IT, role="coordinator")


def _start(task: str = "Vorrei donare 40 kg di pasta", max_steps: int = 12) -> tuple[uuid.UUID, dict]:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        return start_run(session, IT_COORDINATOR, task, "agents-test", max_steps=max_steps)


def _run_state(run_id: uuid.UUID) -> tuple[str, list[tuple[int, str, str]], list[str]]:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        status = session.execute(text("SELECT status FROM agent_run WHERE id = :id"), {"id": run_id}).scalar_one()
        steps = session.execute(
            text("SELECT seq, agent, status FROM agent_step WHERE run_id = :id ORDER BY seq"), {"id": run_id}
        ).all()
        findings = [m.content for m in recall(session, scope="run", run_id=run_id, kinds=("finding",))]
    return status, [tuple(s) for s in steps], findings


def test_run_flows_through_supervisor_plan_and_specialists(monkeypatch) -> None:
    class Gateway:
        def call(self, invocation):
            return {"hits": [], "query": invocation.arguments["query"]}

    monkeypatch.setattr(ToolGatewayClient, "from_environment", classmethod(lambda cls: Gateway()))
    run_id, message = _start()
    queue = MemoryQueue()
    queue.send(message)

    assert drain(queue) == 7
    status, steps, findings = _run_state(run_id)
    assert status == "succeeded"
    assert steps == [
        (1, "supervisor", "succeeded"),
        (2, "intake", "succeeded"),
        (3, "supervisor", "succeeded"),
        (4, "donation_operations", "succeeded"),
        (5, "supervisor", "succeeded"),
        (6, "compliance_review", "succeeded"),
        (7, "supervisor", "succeeded"),
    ]
    assert "route:donation_offer:ok" in findings
    assert any(f.startswith("plan:") for f in findings)
    assert any(f.startswith("result:donation_operations:") for f in findings)
    assert any(f.startswith("result:compliance_review:") for f in findings)
    assert any(f.startswith("summary:") for f in findings)
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        routed = session.execute(
            text("SELECT router, shadow, route FROM routing_decision WHERE request_id = :id"), {"id": run_id}
        ).all()
    assert [tuple(r) for r in routed] == [("baseline", False, "donation_offer")]


def test_redelivered_message_does_not_run_the_step_again() -> None:
    _, message = _start()
    queue = MemoryQueue()
    assert execute(message, AGENTS, queue) == "continue"
    assert execute(message, AGENTS, queue) == "not_claimable"
    assert len(queue.messages) == 1  # only one follow-up step was enqueued


def test_workflow_retry_advances_from_the_step_committed_in_aurora() -> None:
    run_id, message = _start()
    assert execute(message, AGENTS, MemoryQueue(), dispatch_next=False) == "continue"
    assert workflow_resume(TENANT_IT, run_id, 1) == "advance"


def test_workflow_retry_waits_while_the_original_step_still_holds_its_lease() -> None:
    run_id, _ = _start()
    assert not isinstance(_claim(TENANT_IT, run_id, 1), str)
    assert workflow_resume(TENANT_IT, run_id, 1) == "wait"


def test_two_workers_on_the_same_step_only_one_executes() -> None:
    _, message = _start()
    queue = MemoryQueue()
    start = threading.Barrier(2)

    def worker(_: int) -> str:
        start.wait(timeout=10)
        return execute(message, AGENTS, queue)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(worker, range(2)))
    assert outcomes == ["continue", "not_claimable"]
    assert len(queue.messages) == 1


def test_worker_that_lost_its_lease_cannot_complete(owner) -> None:
    run_id, message = _start()
    context, attempt, _ = _claim(TENANT_IT, run_id, 1)
    owner.execute(text("UPDATE agent_step SET lease_until = now() - interval '1 second' WHERE run_id = :id"), {"id": run_id})

    assert execute(message, AGENTS, MemoryQueue()) == "continue"  # a second worker takes over
    late = _complete(context, attempt, StepResult(outcome="succeeded"), latency_ms=1)
    assert late is False
    status, steps, _ = _run_state(run_id)
    assert (status, steps[0][2]) == ("running", "succeeded")


def test_step_budget_ends_the_run_as_budget_exhausted() -> None:
    run_id, message = _start(max_steps=1)
    queue = MemoryQueue()
    assert execute(message, AGENTS, queue) == "budget_exhausted"
    status, steps, _ = _run_state(run_id)
    assert status == "budget_exhausted"
    assert steps == [(1, "supervisor", "succeeded")]
    assert not queue.messages


def test_unknown_agent_fails_the_run_instead_of_hanging() -> None:
    run_id, message = _start()
    assert execute(message, {}, MemoryQueue()) == "failed"
    status, steps, _ = _run_state(run_id)
    assert (status, steps) == ("failed", [(1, "supervisor", "failed")])


def test_message_with_another_tenant_cannot_reach_the_run() -> None:
    _, message = _start()
    forged = message | {"tenant_id": str(TENANT_DK)}
    assert execute(forged, AGENTS, MemoryQueue()) == "missing"


def test_requeue_resends_steps_whose_message_was_lost(owner, maintenance_engine) -> None:
    run_id, _ = _start()  # message never sent: simulates a failed send after commit
    owner.execute(text("UPDATE agent_step SET created_at = now() - interval '5 minutes' WHERE run_id = :id"), {"id": run_id})
    queue = MemoryQueue()
    with maintenance_engine.connect() as connection:
        requeue_stale(connection, queue)
    assert {"tenant_id": str(TENANT_IT), "run_id": str(run_id), "seq": 1} in [
        {k: m[k] for k in ("tenant_id", "run_id", "seq")} for m in queue.messages
    ]
