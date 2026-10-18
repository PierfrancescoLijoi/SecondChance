"""Tenant-scoped database access (ADR-003).

The API connects as `secondchance_app`, which owns no table and has no BYPASSRLS, so the
RLS policies decide which rows exist for each transaction.
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from secondchance.dbconn import make_engine

engine = make_engine(os.environ["SECONDCHANCE_DATABASE_URL"])
SessionLocal = sessionmaker(engine)


@contextmanager
def tenant_transaction(tenant_id: uuid.UUID, role: str, subject: str | None = None) -> Iterator[Session]:
    """One transaction with app.tenant_id, app.role and app.subject set for its lifetime only."""
    with SessionLocal.begin() as session:
        # set_config(..., true) is SET LOCAL with bind parameters: the values vanish
        # at commit/rollback, so a pooled connection never carries them over.
        session.execute(
            text(
                "SELECT set_config('app.tenant_id', :tenant_id, true),"
                " set_config('app.role', :role, true),"
                " set_config('app.subject', :subject, true)"
            ),
            {"tenant_id": str(tenant_id), "role": role, "subject": subject or ""},
        )
        yield session


@contextmanager
def subject_transaction(subject: str) -> Iterator[Session]:
    """No tenant yet: only the subject's own memberships are visible (ADR-017)."""
    with SessionLocal.begin() as session:
        session.execute(text("SELECT set_config('app.subject', :subject, true)"), {"subject": subject})
        yield session
