"""ADR-014: retention runs as a narrow maintenance role and deletes only what expired."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from secondchance.agents.runtime import start_run
from secondchance.identity import Claims
from secondchance.db import tenant_transaction
from secondchance.retention import purge
from secondchance.seed import TENANT_IT


def test_purge_deletes_expired_rows_and_keeps_fresh_ones(owner, maintenance_engine) -> None:
    claims = Claims(sub="coord-it", tenant_id=TENANT_IT, role="coordinator")
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        old_run, _ = start_run(session, claims, "vecchio", "retention-test")
        new_run, _ = start_run(session, claims, "nuovo", "retention-test")
    owner.execute(
        text("UPDATE agent_memory SET created_at = now() - interval '9 days', expires_at = now() - interval '2 days'"
             " WHERE run_id = :run"),
        {"run": old_run},
    )
    owner.execute(text("UPDATE agent_step SET created_at = now() - interval '400 days' WHERE run_id = :run"), {"run": old_run})
    owner.execute(text("UPDATE agent_run SET created_at = now() - interval '400 days' WHERE id = :run"), {"run": old_run})

    with maintenance_engine.begin() as connection:
        deleted = purge(connection)

    remaining = {
        run: owner.execute(text("SELECT count(*) FROM agent_run WHERE id = :run"), {"run": run}).scalar_one()
        for run in (old_run, new_run)
    }
    assert deleted["agent_memory"] >= 1 and deleted["agent_run"] >= 1
    assert remaining == {old_run: 0, new_run: 1}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_event SET outcome = 'failed'",
        "INSERT INTO agent_memory (scope, kind, content, source, expires_at, tenant_id)"
        " SELECT 'tenant', 'fact', 'x', 'operator', now() + interval '1 day', id FROM tenant LIMIT 1",
        "SELECT * FROM donation_offer",
        "DELETE FROM tenant",
    ],
)
def test_maintenance_role_can_only_read_and_delete_what_retention_needs(maintenance_engine, statement: str) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        with maintenance_engine.begin() as connection:
            connection.execute(text(statement))


def test_operational_records_expire_but_live_missions_stay(owner, maintenance_engine) -> None:
    import uuid

    from secondchance.notifications import notify

    old_id, fresh_id = uuid.uuid4(), uuid.uuid4()
    with tenant_transaction(TENANT_IT, "coordinator", "demo-it-coordinator") as session:
        notify(session, recipient="demo-it-volunteer", kind="mission_assigned", object_type="mission", object_id=old_id)
        notify(session, recipient="demo-it-volunteer", kind="mission_assigned", object_type="mission", object_id=fresh_id)
    owner.execute(text("UPDATE notification SET created_at = now() - interval '200 days' WHERE object_id = :id"), {"id": old_id})

    with maintenance_engine.begin() as connection:
        deleted = purge(connection)

    left = {
        key: owner.execute(text("SELECT count(*) FROM notification WHERE object_id = :id"), {"id": key}).scalar_one()
        for key in (old_id, fresh_id)
    }
    assert left == {old_id: 0, fresh_id: 1}  # the outbox row of the old one went with it (ON DELETE CASCADE)
    assert {"notification", "notification_delivery", "mission_event", "mission", "allocation_proposal",
            "matching_run"} <= set(deleted)
