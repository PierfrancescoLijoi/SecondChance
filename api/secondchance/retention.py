"""Retention as code (ADR-014). `python -m secondchance.retention`, daily (EventBridge Scheduler on AWS).

Runs as secondchance_maintenance (db/bootstrap.sql): the API role cannot delete, by design.
Order respects foreign keys.
"""

import os
from datetime import timedelta

from sqlalchemy import Connection, text

from secondchance.dbconn import make_engine

RETENTION: dict[str, timedelta] = {
    "experiment_exposure": timedelta(days=180),
    "routing_decision": timedelta(days=365),
    "agent_step": timedelta(days=365),
    "agent_run": timedelta(days=365),
    "audit_event": timedelta(days=5 * 365),  # to validate with the pilot's legal counsel
    "notification": timedelta(days=90),
    "notification_delivery": timedelta(days=30),
    "mission": timedelta(days=730),  # finished missions: two seasons of comparable impact figures
    "allocation_proposal": timedelta(days=365),
    "matching_run": timedelta(days=365),
}

_STATEMENTS: tuple[tuple[str, str], ...] = (
    ("agent_memory", "DELETE FROM agent_memory WHERE expires_at <= now()"),
    ("experiment_exposure", "DELETE FROM experiment_exposure WHERE occurred_at < now() - :age"),
    ("routing_decision", "DELETE FROM routing_decision WHERE created_at < now() - :age"),
    ("agent_step", "DELETE FROM agent_step WHERE created_at < now() - :age"),
    (
        "agent_run",
        "DELETE FROM agent_run r WHERE r.created_at < now() - :age"
        " AND NOT EXISTS (SELECT 1 FROM agent_step s WHERE s.run_id = r.id)"
        " AND NOT EXISTS (SELECT 1 FROM agent_memory m WHERE m.run_id = r.id)",
    ),
    ("audit_event", "DELETE FROM audit_event WHERE occurred_at < now() - :age"),
    ("notification_delivery", "DELETE FROM notification_delivery WHERE created_at < now() - :age"),
    ("notification", "DELETE FROM notification WHERE created_at < now() - :age"),
    # A mission and its history go together, only once it is over (delivered, failed or cancelled).
    (
        "mission_event",
        "DELETE FROM mission_event e USING mission m WHERE e.mission_id = m.id"
        " AND m.status IN ('delivered', 'failed', 'cancelled') AND m.updated_at < now() - :age",
    ),
    (
        "mission",
        "DELETE FROM mission m WHERE m.status IN ('delivered', 'failed', 'cancelled') AND m.updated_at < now() - :age"
        " AND NOT EXISTS (SELECT 1 FROM mission_event e WHERE e.mission_id = m.id)",
    ),
    (
        "allocation_proposal",
        "DELETE FROM allocation_proposal p WHERE p.created_at < now() - :age"
        " AND NOT EXISTS (SELECT 1 FROM mission m WHERE m.proposal_id = p.id)",
    ),
    (
        "matching_run",
        "DELETE FROM matching_run r WHERE r.created_at < now() - :age"
        " AND NOT EXISTS (SELECT 1 FROM allocation_proposal p WHERE p.run_id = r.id)",
    ),
)
# The history of a mission shares the mission's retention.
_AGE_OF = {"mission_event": "mission"}


def purge(connection: Connection) -> dict[str, int]:
    deleted = {}
    for table, statement in _STATEMENTS:
        key = _AGE_OF.get(table, table)
        params = {"age": RETENTION[key]} if key in RETENTION else {}
        deleted[table] = connection.execute(text(statement), params).rowcount
    return deleted


if __name__ == "__main__":
    with make_engine(os.environ["SECONDCHANCE_MAINTENANCE_URL"]).begin() as connection:
        print(purge(connection))
