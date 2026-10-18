"""Jobs worker: `python -m secondchance.jobs`. Consumes the `jobs` queue (ingestion; the solver in P2).

Stateless like the agents worker; on AWS the same `handle` runs in a Lambda.
"""

import logging
import os
import sys
import uuid
from datetime import timedelta

from sqlalchemy import Connection, text

from secondchance.db import engine
from secondchance.dbconn import make_engine
from secondchance.knowledge import ingest
from secondchance.observability import configure_logging, configure_telemetry
from secondchance.queues import MalformedMessage, Queue, SqsQueue, drain, require

log = logging.getLogger(__name__)
STALE_UPLOAD = timedelta(minutes=2)


def handle(body: object) -> str:
    message = require(body, "type", "tenant_id")
    if message["type"] == "ingest":
        require(message, "version_id")
        return ingest.process(uuid.UUID(message["tenant_id"]), uuid.UUID(message["version_id"]))
    raise MalformedMessage(f"unknown job type {message['type']!r}")


def requeue_stale(connection: Connection, queue: Queue) -> int:
    """Uploads whose message was lost, and jobs whose worker died (as secondchance_maintenance)."""
    rows = connection.execute(
        text(
            "SELECT tenant_id, id FROM document_version"
            " WHERE (status = 'uploaded' AND created_at < now() - :stale)"
            " OR (status = 'processing' AND lease_until < now())"
        ),
        {"stale": STALE_UPLOAD},
    ).all()
    for tenant_id, version_id in rows:
        queue.send({"type": "ingest", "tenant_id": str(tenant_id), "version_id": str(version_id)})
    return len(rows)


if __name__ == "__main__":
    configure_logging()
    configure_telemetry(engine=engine)
    queue = SqsQueue(os.environ.get("SECONDCHANCE_QUEUE_JOBS", "jobs"))
    if "--requeue" in sys.argv:
        with make_engine(os.environ["SECONDCHANCE_MAINTENANCE_URL"]).connect() as connection:
            log.info("re-queued %s stale ingestion jobs", requeue_stale(connection, queue))
    else:
        drain(queue, handle, wait_seconds=10)
