"""The real local adapters: ElasticMQ (SQS API) and SeaweedFS (S3 API) from the Compose stack."""

import os
import uuid

import boto3
import pytest
from sqlalchemy import text

from secondchance import storage
from secondchance.agents.runtime import start_run
from secondchance.agents.worker import drain
from secondchance.identity import Claims
from secondchance.db import SessionLocal, tenant_transaction
from secondchance.queues import SqsQueue
from secondchance.seed import TENANT_DK, TENANT_IT


@pytest.fixture
def sqs_queue():
    client = boto3.client("sqs", endpoint_url=os.environ["SECONDCHANCE_SQS_ENDPOINT"], region_name=os.environ["AWS_REGION"])
    name = f"test-agents-{uuid.uuid4().hex[:8]}"  # never the stack's own `agents` queue
    url = client.create_queue(QueueName=name)["QueueUrl"]
    yield SqsQueue(name, client)
    client.delete_queue(QueueUrl=url)


def test_sqs_round_trip_carries_ids_and_correlation(sqs_queue) -> None:
    sqs_queue.send({"run_id": "r1", "seq": 1, "correlation_id": "cid-1"})
    [(receipt, body)] = sqs_queue.receive(wait_seconds=1)
    sqs_queue.delete(receipt)
    assert body == {"run_id": "r1", "seq": 1, "correlation_id": "cid-1"}
    assert sqs_queue.receive() == []


def test_agent_run_end_to_end_through_sqs(sqs_queue) -> None:
    claims = Claims(sub="coord-it", tenant_id=TENANT_IT, role="coordinator")
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        run_id, message = start_run(session, claims, "Il centro ha nuovi orari di apertura", "sqs-test")
    sqs_queue.send(message)
    assert drain(sqs_queue, max_batches=10) == 7
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        status = session.execute(
            text("SELECT status FROM agent_run WHERE id = :id"), {"id": run_id}
        ).scalar_one()
    assert status == "succeeded"


@pytest.fixture(scope="module")
def s3():
    client = storage.client()
    storage.ensure_bucket(client)
    return client


def test_objects_live_under_the_transaction_tenant(s3) -> None:
    for tenant, payload in ((TENANT_IT, b"it"), (TENANT_DK, b"dk")):
        with tenant_transaction(tenant, "coordinator") as session:
            key = storage.put(session, "artifacts", "solver-input.json", payload, "application/json", s3=s3)
            assert key == f"tenants/{tenant}/artifacts/solver-input.json"
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        assert storage.get(session, "artifacts", "solver-input.json", s3=s3) == b"it"


def test_no_tenant_no_object_key(s3) -> None:
    with SessionLocal() as session, pytest.raises(PermissionError):
        storage.object_key(session, "artifacts", "x.json")


@pytest.mark.parametrize(("area", "name"), [("secrets", "x"), ("artifacts", "../other-tenant/x"), ("documents", "")])
def test_unsafe_keys_are_rejected(area: str, name: str) -> None:
    with tenant_transaction(TENANT_IT, "coordinator") as session, pytest.raises(ValueError):
        storage.object_key(session, area, name)
