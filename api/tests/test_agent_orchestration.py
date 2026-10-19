"""AWS orchestration contracts: Standard Step Functions owns the durable run loop."""

import json
import uuid
from datetime import datetime, timezone

from botocore.stub import Stubber
from botocore.exceptions import ClientError
import boto3

from secondchance.agents.dispatch import StepFunctionsDispatcher

FAKE = {"region_name": "eu-central-1", "aws_access_key_id": "test", "aws_secret_access_key": "test"}


def test_step_functions_dispatcher_starts_one_named_execution_per_run() -> None:
    run_id = uuid.uuid4()
    message = {
        "tenant_id": str(uuid.uuid4()),
        "run_id": str(run_id),
        "seq": 1,
        "correlation_id": "request-123",
    }
    client = boto3.client("stepfunctions", **FAKE)
    stub = Stubber(client)
    state_machine = "arn:aws:states:eu-central-1:123456789012:stateMachine:secondchance-demo-agents"
    stub.add_response(
        "start_execution",
        {
            "executionArn": f"arn:aws:states:eu-central-1:123456789012:execution:secondchance-demo-agents:run-{run_id}",
            "startDate": datetime.now(timezone.utc),
        },
        {"stateMachineArn": state_machine, "name": f"run-{run_id}", "input": json.dumps(message, separators=(",", ":"))},
    )

    with stub:
        StepFunctionsDispatcher(state_machine, client=client).send(message)


def test_step_functions_dispatcher_requires_a_run_identifier() -> None:
    client = boto3.client("stepfunctions", **FAKE)
    dispatcher = StepFunctionsDispatcher("arn:aws:states:eu-central-1:123456789012:stateMachine:test", client=client)

    try:
        dispatcher.send({"tenant_id": str(uuid.uuid4()), "seq": 1})
    except ValueError as exc:
        assert str(exc) == "run_id is required for a Step Functions execution"
    else:
        raise AssertionError("missing run_id was accepted")


def test_recovery_treats_an_existing_named_execution_as_success() -> None:
    class Client:
        def start_execution(self, **_):
            raise ClientError(
                {"Error": {"Code": "ExecutionAlreadyExists", "Message": "already running"}},
                "StartExecution",
            )

    StepFunctionsDispatcher(
        "arn:aws:states:eu-central-1:123456789012:stateMachine:test",
        client=Client(),
    ).send({"tenant_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4()), "seq": 1})


def test_recovery_redrives_a_failed_standard_workflow() -> None:
    run_id = uuid.uuid4()
    state_machine = "arn:aws:states:eu-central-1:123456789012:stateMachine:secondchance-agents"
    execution = f"arn:aws:states:eu-central-1:123456789012:execution:secondchance-agents:run-{run_id}"

    class Client:
        def __init__(self):
            self.redriven = None

        def start_execution(self, **_):
            raise ClientError(
                {"Error": {"Code": "ExecutionAlreadyExists", "Message": "failed execution exists"}},
                "StartExecution",
            )

        def describe_execution(self, **kwargs):
            assert kwargs == {"executionArn": execution}
            return {"status": "FAILED"}

        def redrive_execution(self, **kwargs):
            self.redriven = kwargs

    client = Client()
    StepFunctionsDispatcher(state_machine, client=client, recover=True).send({"run_id": str(run_id), "seq": 1})
    assert client.redriven == {"executionArn": execution}
