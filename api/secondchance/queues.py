"""Work hand-off between stateless services (ADR-005, ADR-011): SQS on AWS, ElasticMQ locally.

Messages carry identifiers only, never content, so nothing personal sits in a queue.
"""

import json
import logging
import os
import uuid
from collections import deque
from typing import Protocol

from secondchance.observability import correlation_id, current_correlation_id

log = logging.getLogger("secondchance.worker")


class Queue(Protocol):
    def send(self, body: dict) -> None: ...

    def receive(self, max_messages: int = 10, wait_seconds: int = 0) -> list[tuple[str, dict]]: ...

    def delete(self, receipt: str) -> None: ...


class MemoryQueue:
    """In-process queue for tests and single-process runs."""

    def __init__(self) -> None:
        self.messages: deque[dict] = deque()

    def send(self, body: dict) -> None:
        self.messages.append(body)

    def receive(self, max_messages: int = 10, wait_seconds: int = 0) -> list[tuple[str, dict]]:
        taken = [self.messages.popleft() for _ in range(min(max_messages, len(self.messages)))]
        return [(str(i), body) for i, body in enumerate(taken)]

    def delete(self, receipt: str) -> None:
        pass  # receive() already removed it


class SqsQueue:
    """Same boto3 code against SQS or ElasticMQ; SECONDCHANCE_SQS_ENDPOINT selects ElasticMQ."""

    def __init__(self, name: str, client=None) -> None:
        if client is None:
            import boto3

            client = boto3.client(
                "sqs",
                endpoint_url=os.environ.get("SECONDCHANCE_SQS_ENDPOINT"),
                region_name=os.environ.get("AWS_REGION", "eu-central-1"),
            )
        self.client = client
        self.url = client.get_queue_url(QueueName=name)["QueueUrl"]

    def send(self, body: dict) -> None:
        self.client.send_message(
            QueueUrl=self.url,
            MessageBody=json.dumps(body),
            MessageAttributes={
                "correlation_id": {"DataType": "String", "StringValue": body.get("correlation_id") or current_correlation_id()}
            },
        )

    def receive(self, max_messages: int = 10, wait_seconds: int = 0) -> list[tuple[str, dict]]:
        response = self.client.receive_message(
            QueueUrl=self.url, MaxNumberOfMessages=max_messages, WaitTimeSeconds=wait_seconds
        )
        return [(m["ReceiptHandle"], json.loads(m["Body"])) for m in response.get("Messages", [])]

    def delete(self, receipt: str) -> None:
        self.client.delete_message(QueueUrl=self.url, ReceiptHandle=receipt)


def drain(queue: Queue, handler, wait_seconds: int = 0, max_batches: int | None = None) -> int:
    """Processes messages until the queue is empty (or max_batches). Returns how many ran.

    A message whose handler raises stays in the queue for redelivery and, after
    maxReceiveCount attempts, moves to the DLQ. Malformed messages are deleted at once.
    """
    done, batches = 0, 0
    while max_batches is None or batches < max_batches:
        batch = queue.receive(max_messages=10, wait_seconds=wait_seconds)
        batches += 1
        if not batch and wait_seconds == 0:
            return done
        for receipt, body in batch:
            token = correlation_id.set(str(body.get("correlation_id", "")) if isinstance(body, dict) else "")
            try:
                outcome = handler(body)
                log.info("message handled: %s", outcome)
                queue.delete(receipt)
                done += 1
            except MalformedMessage as error:
                log.warning("malformed message dropped: %s", error)
                queue.delete(receipt)
            except Exception:
                log.exception("handler failed; message left for redelivery")
            finally:
                correlation_id.reset(token)
    return done


class MalformedMessage(ValueError):
    """Schema check failed before any work (ADR-016, stage 9): retrying cannot help."""


def require(body: object, *fields: str) -> dict:
    if not isinstance(body, dict):
        raise MalformedMessage("body is not an object")
    for name in fields:
        if name not in body:
            raise MalformedMessage(f"missing {name}")
        if name.endswith("_id"):
            try:
                uuid.UUID(str(body[name]))
            except ValueError as exc:
                raise MalformedMessage(f"{name} is not a UUID") from exc
    return body
