"""Append-only audit trail (FR-004): written in the same transaction as the change it records."""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def record(
    session: Session,
    actor: str,
    actor_role: str,
    action: str,
    object_type: str,
    object_id: uuid.UUID | None,
    correlation_id: str,
    details: dict | None = None,
    outcome: str = "success",
) -> None:
    """Identifiers and codes only in `details`: no free text, no contact data."""
    session.execute(
        text(
            "INSERT INTO audit_event (actor, actor_role, action, object_type, object_id, outcome, correlation_id, details)"
            " VALUES (:actor, :role, :action, :type, :id, :outcome, :cid, CAST(:details AS jsonb))"
        ),
        {
            "actor": actor, "role": actor_role, "action": action, "type": object_type, "id": object_id,
            "outcome": outcome, "cid": correlation_id, "details": json.dumps(details or {}, default=str),
        },
    )
