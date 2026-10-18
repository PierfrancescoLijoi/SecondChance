"""ADR-011: memory shared by agents, isolated by tenant and scope, always expiring."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from secondchance.agents.runtime import start_run
from secondchance.identity import Claims
from secondchance.db import tenant_transaction
from secondchance.memory import EMBEDDING_DIMENSIONS, recall, recall_similar, remember
from secondchance.seed import TENANT_DK, TENANT_IT

IT_COORDINATOR = Claims(sub="coord-it", tenant_id=TENANT_IT, role="coordinator")


def _run(task: str = "Abbiamo 40 kg di pasta da donare") -> uuid.UUID:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        run_id, _ = start_run(session, IT_COORDINATOR, task, "memory-test")
    return run_id


def _unit_vector(position: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[position] = 1.0
    return vector


def test_run_memory_is_shared_within_the_run_only() -> None:
    run_a, run_b = _run(), _run()
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        remember(session, scope="run", run_id=run_a, kind="finding", content="route:donation_offer:ok", source="intake")
        seen_a = [m.content for m in recall(session, scope="run", run_id=run_a, kinds=("finding",))]
        seen_b = [m.content for m in recall(session, scope="run", run_id=run_b, kinds=("finding",))]
    assert seen_a == ["route:donation_offer:ok"]
    assert seen_b == []


def test_other_tenant_sees_no_memory() -> None:
    run_id = _run()
    with tenant_transaction(TENANT_DK, "coordinator") as session:
        assert recall(session, scope="run", run_id=run_id) == []


def test_conversation_memory_is_per_subject() -> None:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        remember(session, scope="conversation", subject="alice", kind="message", content="ciao", source="operator")
        assert [m.content for m in recall(session, scope="conversation", subject="alice")][:1] == ["ciao"]
        assert recall(session, scope="conversation", subject="bob") == []


def test_content_is_redacted_before_it_is_stored() -> None:
    run_id = _run("Contattare mario.rossi@example.org per il ritiro")
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        task = recall(session, scope="run", run_id=run_id, kinds=("task",))
    assert task[0].content == "Contattare [EMAIL] per il ritiro"


def test_tenant_memory_only_from_operators() -> None:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        with pytest.raises(ValueError):
            remember(session, scope="tenant", kind="fact", content="model guess", source="knowledge")
    with pytest.raises(IntegrityError):  # the database refuses it too
        with tenant_transaction(TENANT_IT, "coordinator") as session:
            session.execute(
                text(
                    "INSERT INTO agent_memory (scope, kind, content, source, expires_at)"
                    " VALUES ('tenant', 'fact', 'model guess', 'knowledge', now() + interval '1 day')"
                )
            )


def test_expired_memory_is_not_recalled(owner) -> None:
    run_id = _run()
    owner.execute(
        text("UPDATE agent_memory SET created_at = now() - interval '9 days', expires_at = now() - interval '1 day'"
             " WHERE run_id = :run"),
        {"run": run_id},
    )
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        assert recall(session, scope="run", run_id=run_id) == []


def test_similarity_search_ranks_and_ignores_other_models() -> None:
    run_id = _run()
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        for i, content in enumerate(["frigo pieno", "orari del centro"]):
            remember(session, scope="run", run_id=run_id, kind="finding", content=content, source="knowledge",
                     embedding=_unit_vector(i), embedding_model="test-embed-1024")
        remember(session, scope="run", run_id=run_id, kind="finding", content="altro modello", source="knowledge",
                 embedding=_unit_vector(0), embedding_model="other-model")
        hits = recall_similar(session, scope="run", run_id=run_id, embedding=_unit_vector(0),
                              embedding_model="test-embed-1024")
    assert [m.content for m, _ in hits] == ["frigo pieno", "orari del centro"]
    assert hits[0][1] == pytest.approx(0.0)
