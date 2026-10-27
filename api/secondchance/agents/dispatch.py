"""Durable agent-run dispatchers.

AWS uses a Standard Step Functions execution per run. Local development and the
recovery job keep using the Queue protocol, so the domain runtime stays portable.
"""

import json
import os

from botocore.exceptions import ClientError


class StepFunctionsDispatcher:
    """Start one idempotently named Standard Workflow execution per agent run."""

    def __init__(self, state_machine_arn: str, client=None, *, recover: bool = False) -> None:
        if client is None:
            import boto3

            client = boto3.client("stepfunctions", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
        self.state_machine_arn = state_machine_arn
        self.client = client
        self.recover = recover

    def send(self, body: dict) -> None:
        run_id = body.get("run_id")
        if not run_id:
            raise ValueError("run_id is required for a Step Functions execution")
        try:
            self.client.start_execution(
                stateMachineArn=self.state_machine_arn,
                name=f"run-{run_id}",
                input=json.dumps(body, separators=(",", ":")),
            )
        except ClientError as exc:
            # Standard Workflow execution names are unique for 90 days. A recovery
            # scan may rediscover the first pending step after the workflow started;
            # that duplicate is success, not a second orchestration.
            if exc.response.get("Error", {}).get("Code") != "ExecutionAlreadyExists":
                raise
            if self.recover:
                execution_arn = self.state_machine_arn.replace(":stateMachine:", ":execution:") + f":run-{run_id}"
                status = self.client.describe_execution(executionArn=execution_arn)["status"]
                if status in {"FAILED", "TIMED_OUT", "ABORTED", "PENDING_REDRIVE"}:
                    self.client.redrive_execution(executionArn=execution_arn)


def configured_dispatcher(*, recover: bool = False):
    """Return the AWS workflow dispatcher, or the portable queue fallback."""
    state_machine = os.environ.get("SECONDCHANCE_AGENT_STATE_MACHINE_ARN")
    if state_machine:
        return StepFunctionsDispatcher(state_machine, recover=recover)
    from secondchance.queues import open_queue

    return open_queue("SECONDCHANCE_QUEUE_AGENTS", "agents")
