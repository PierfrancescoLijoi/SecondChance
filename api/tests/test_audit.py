"""FR-004: the app role can append to and read its own audit log, never rewrite it."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from secondchance.db import tenant_transaction
from secondchance.seed import TENANT_DK, TENANT_IT

COUNT_BY_CID = text("SELECT count(*) FROM audit_event WHERE correlation_id = :cid")


def _append(cid: str) -> None:
    with tenant_transaction(TENANT_IT, "org_admin") as session:
        session.execute(
            text(
                "INSERT INTO audit_event (actor, actor_role, action, object_type, outcome, correlation_id)"
                " VALUES ('tester', 'org_admin', 'test.append', 'audit_event', 'success', :cid)"
            ),
            {"cid": cid},
        )


def test_append_is_visible_to_own_tenant_only() -> None:
    cid = str(uuid.uuid4())
    _append(cid)
    with tenant_transaction(TENANT_IT, "org_admin") as session:
        assert session.execute(COUNT_BY_CID, {"cid": cid}).scalar_one() == 1
    with tenant_transaction(TENANT_DK, "org_admin") as session:
        assert session.execute(COUNT_BY_CID, {"cid": cid}).scalar_one() == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_event SET outcome = 'failed'",
        "DELETE FROM audit_event",
        "TRUNCATE audit_event",
    ],
)
def test_audit_cannot_be_rewritten(statement: str) -> None:
    cid = str(uuid.uuid4())
    _append(cid)
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_transaction(TENANT_IT, "platform_admin") as session:
            session.execute(text(statement))
    with tenant_transaction(TENANT_IT, "org_admin") as session:
        assert session.execute(COUNT_BY_CID, {"cid": cid}).scalar_one() == 1
