"""In-app notifications and the email outbox (FR-026).

A notification row is written in the same transaction as the change it announces. Kinds that
also go by email get an outbox row; after the commit the API hands a message to the `notify`
queue and marks the row queued. If that hand-off fails, the requeue job sends every pending row
older than a minute. Messages carry identifiers and codes only: the notifier resolves the address
from the identity provider and the text from a template, so no content and no beneficiary data
ever sits in a queue (ADR-005).
"""

import logging
import os
import uuid
from datetime import timedelta
from functools import lru_cache

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from secondchance.db import tenant_transaction
from secondchance.observability import current_correlation_id, meter
from secondchance.queues import Queue

log = logging.getLogger(__name__)

EMAIL_KINDS = frozenset({"mission_assigned", "mission_cancelled"})
LANGUAGES = {"IT": "it", "DK": "da", "PL": "pl"}  # anything else: English
STALE_OUTBOX = timedelta(minutes=1)
OUTBOX_ROLE = "notifier"

handoffs = meter.create_counter("secondchance.notifications.handoffs", description="Email outbox hand-offs by outcome")


@lru_cache
def notify_queue() -> Queue:
    from secondchance.queues import SqsQueue

    return SqsQueue(os.environ.get("SECONDCHANCE_QUEUE_NOTIFY", "notify"))


def network_language(session: Session) -> str:
    country = session.execute(text("SELECT country FROM tenant WHERE id = current_tenant_id()")).scalar_one_or_none()
    return LANGUAGES.get(country or "", "en")


def notify(
    session: Session, *, recipient: str, kind: str, object_type: str, object_id: uuid.UUID, language: str = "en"
) -> dict | None:
    """In-app row for `recipient`; for email kinds also an outbox row and the message to send after commit.

    No RETURNING: the row belongs to the recipient, so RLS hides it from the operator who creates it.
    """
    notification_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO notification (id, recipient, kind, object_type, object_id)"
            " VALUES (:id, :recipient, :kind, :type, :object)"
        ),
        {"id": notification_id, "recipient": recipient, "kind": kind, "type": object_type, "object": object_id},
    )
    if kind not in EMAIL_KINDS:
        return None
    delivery_id = uuid.uuid4()
    session.execute(
        text("INSERT INTO notification_delivery (id, notification_id, language) VALUES (:id, :notification, :language)"),
        {"id": delivery_id, "notification": notification_id, "language": language},
    )
    tenant_id = session.execute(text("SELECT current_tenant_id()")).scalar_one()
    return message(tenant_id, delivery_id, recipient, kind, language, current_correlation_id())


def message(tenant_id, delivery_id, recipient: str, kind: str, language: str, correlation_id: str) -> dict:
    return {
        "type": "email", "tenant_id": str(tenant_id), "delivery_id": str(delivery_id), "recipient": recipient,
        "kind": kind, "language": language, "correlation_id": correlation_id,
    }


def dispatch(tenant_id: uuid.UUID, messages: list[dict | None], queue: Queue) -> int:
    """After the commit. A failed send leaves the row pending for the requeue job: never fails the request."""
    sent = 0
    for body in filter(None, messages):
        try:
            queue.send(body)
        except Exception:  # noqa: BLE001 - the outbox row stays pending and is retried
            log.exception("notification hand-off failed; the requeue job will retry")
            handoffs.add(1, {"outcome": "deferred"})
            continue
        with tenant_transaction(tenant_id, OUTBOX_ROLE) as session:
            session.execute(
                text(
                    "UPDATE notification_delivery SET status = 'queued', attempts = attempts + 1, queued_at = now()"
                    " WHERE id = :id AND status = 'pending'"
                ),
                {"id": body["delivery_id"]},
            )
        handoffs.add(1, {"outcome": "queued"})
        sent += 1
    return sent


def requeue_pending(connection: Connection, queue: Queue) -> int:
    """Outbox rows whose hand-off failed (as secondchance_maintenance, inside a transaction)."""
    rows = connection.execute(
        text(
            "SELECT d.id, d.tenant_id, d.language, n.recipient, n.kind FROM notification_delivery d"
            " JOIN notification n ON n.id = d.notification_id"
            " WHERE d.status = 'pending' AND d.created_at < now() - :stale"
            " ORDER BY d.created_at LIMIT 500"
        ),
        {"stale": STALE_OUTBOX},
    ).all()
    for row in rows:
        queue.send(message(row.tenant_id, row.id, row.recipient, row.kind, row.language, f"requeue-{row.id}"))
        connection.execute(
            text(
                "UPDATE notification_delivery SET status = 'queued', attempts = attempts + 1, queued_at = now()"
                " WHERE id = :id"
            ),
            {"id": row.id},
        )
    return len(rows)


def inbox(session: Session, unread_only: bool = False, limit: int = 50) -> tuple[list[dict], int]:
    """The caller's own notifications: RLS keeps everybody else's out, even inside the network."""
    rows = session.execute(
        text(
            "SELECT id, kind, object_type, object_id, created_at, read_at FROM notification"
            " WHERE NOT :unread OR read_at IS NULL ORDER BY created_at DESC, id LIMIT :limit"
        ),
        {"unread": unread_only, "limit": limit},
    ).mappings()
    unread = session.execute(text("SELECT count(*) FROM notification WHERE read_at IS NULL")).scalar_one()
    return [dict(r) for r in rows], unread


def mark_read(session: Session, notification_id: uuid.UUID | None) -> int:
    """One notification, or all of them when `notification_id` is None."""
    return session.execute(
        text(
            "UPDATE notification SET read_at = now()"
            " WHERE read_at IS NULL AND (CAST(:id AS uuid) IS NULL OR id = CAST(:id AS uuid))"
        ),
        {"id": notification_id},
    ).rowcount
