"""Work hand-off between stateless services (ADR-005, ADR-011): SQS on AWS, Service Bus on Azure, ElasticMQ locally.

Messages carry identifiers only, never content, so nothing personal sits in a queue.
"""

import json
import logging
import os
import uuid
from collections import deque
from typing import Protocol

from secondchance.cloud import azure_credential, is_azure
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


class ServiceBusQueue:
    """Azure Service Bus queue behind the same protocol (ADR-023).

    Peek-lock is SQS's visibility timeout: a message that is not completed returns to the queue and,
    after the queue's max delivery count (5), moves to its dead-letter sub-queue, the DLQ of this stack.
    The lock is renewed while the handler runs (a PDF or a solver run outlives the 5 minute maximum lock).
    Authentication is the caller's managed identity; the namespace has local (key) authentication off.
    """

    def __init__(self, name: str, client=None, *, namespace: str | None = None, lock_renewal_seconds: int = 1800) -> None:
        if client is None:
            from azure.servicebus import ServiceBusClient

            client = ServiceBusClient(namespace or os.environ["SECONDCHANCE_SERVICEBUS_NAMESPACE"], azure_credential())
        self.client, self.name = client, name
        self.lock_renewal_seconds = lock_renewal_seconds
        self._sender = None
        self._receiver = None
        self._renewer = None
        self._inflight: dict[str, object] = {}

    def send(self, body: dict) -> None:
        from azure.servicebus import ServiceBusMessage

        message = ServiceBusMessage(
            json.dumps(body), content_type="application/json",
            application_properties={"correlation_id": body.get("correlation_id") or current_correlation_id()},
        )
        try:
            if self._sender is None:
                self._sender = self.client.get_queue_sender(self.name)
            self._sender.send_messages(message)
        except Exception:
            self.close_sender()  # the next call opens a fresh AMQP link
            raise

    def close_sender(self) -> None:
        sender, self._sender = self._sender, None
        if sender is not None:
            try:
                sender.close()
            except Exception:  # noqa: BLE001 - the link may already be gone
                log.debug("service bus sender close failed", exc_info=True)

    def _open_receiver(self):
        if self._receiver is None:
            from azure.servicebus import AutoLockRenewer

            self._renewer = AutoLockRenewer(max_lock_renewal_duration=self.lock_renewal_seconds)
            self._receiver = self.client.get_queue_receiver(self.name, auto_lock_renewer=self._renewer)
        return self._receiver

    def receive(self, max_messages: int = 10, wait_seconds: int = 0) -> list[tuple[str, dict]]:
        receiver = self._open_receiver()
        try:
            messages = receiver.receive_messages(max_message_count=max_messages, max_wait_time=max(wait_seconds, 1))
        except Exception:
            self.close()
            raise
        batch = []
        for message in messages:
            receipt = str(message.lock_token)
            try:
                body = json.loads(b"".join(message.body).decode("utf-8"))
            except (ValueError, TypeError):
                receiver.dead_letter_message(message, reason="MalformedMessage", error_description="body is not JSON")
                continue
            self._inflight[receipt] = message
            batch.append((receipt, body))
        return batch

    def delete(self, receipt: str) -> None:
        self._receiver.complete_message(self._inflight.pop(receipt))

    def release(self, receipt: str) -> None:
        """Hands a failed message back at once; the broker counts the delivery towards the DLQ."""
        self._receiver.abandon_message(self._inflight.pop(receipt))

    def close(self) -> None:
        self.close_sender()
        receiver, self._receiver = self._receiver, None
        self._inflight.clear()
        if receiver is not None:
            try:
                receiver.close()
            except Exception:  # noqa: BLE001
                log.debug("service bus receiver close failed", exc_info=True)


def open_queue(env_name: str, default: str) -> Queue:
    """The named queue on the configured cloud: SQS/ElasticMQ, or Service Bus when SECONDCHANCE_CLOUD=azure."""
    name = os.environ.get(env_name, default)
    return ServiceBusQueue(name) if is_azure() else SqsQueue(name)


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
                release = getattr(queue, "release", None)  # Service Bus: abandon now instead of waiting for the lock
                if release is not None:
                    release(receipt)
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
