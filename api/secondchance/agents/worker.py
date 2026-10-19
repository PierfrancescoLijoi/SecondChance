"""Agent worker: `python -m secondchance.agents.worker`. Stateless, run as many as needed.

Locally it polls ElasticMQ; on AWS the same handler runs in a Lambda behind an SQS
event source mapping. A message that keeps failing lands in the DLQ after maxReceiveCount.
"""

import logging
import os
import sys

from secondchance.agents.builtin import AGENTS
from secondchance.agents.runtime import execute, requeue_stale
from secondchance.db import engine
from secondchance.dbconn import make_engine
from secondchance.observability import configure_logging, configure_telemetry
from secondchance.queues import MalformedMessage, Queue, SqsQueue, require
from secondchance.queues import drain as drain_queue

log = logging.getLogger(__name__)


def handle(body: object, queue: Queue) -> str:
    message = require(body, "tenant_id", "run_id", "seq")
    if not isinstance(message["seq"], int) or message["seq"] < 1:
        raise MalformedMessage("seq must be a positive integer")
    return execute(message, AGENTS, queue)


def drain(queue: Queue, wait_seconds: int = 0, max_batches: int | None = None) -> int:
    return drain_queue(queue, lambda body: handle(body, queue), wait_seconds, max_batches)


if __name__ == "__main__":
    configure_logging()
    configure_telemetry(engine=engine)
    queue = SqsQueue(os.environ.get("SECONDCHANCE_QUEUE_AGENTS", "agents"))
    if "--requeue" in sys.argv:  # scheduled job, with the maintenance role's credentials
        with make_engine(os.environ["SECONDCHANCE_MAINTENANCE_URL"]).connect() as connection:
            log.info("re-queued %s stale steps", requeue_stale(connection, queue))
    else:
        drain(queue, wait_seconds=10)
