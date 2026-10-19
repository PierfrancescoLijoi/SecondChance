"""The gateway's AWS calls against botocore's service models (real clients, Stubber, no network)."""

import io
import json
from unittest.mock import patch

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from mcp_gateway import service
from mcp_gateway.policy import DynamoDBRateLimiter, PolicyDenied

FAKE = {"region_name": "eu-central-1", "aws_access_key_id": "test", "aws_secret_access_key": "test"}


def test_rate_limit_update_item_and_its_rejection_match_the_dynamodb_model() -> None:
    client = boto3.client("dynamodb", **FAKE)
    stub = Stubber(client)
    stub.add_response("update_item", {}, {
        "TableName": "secondchance-demo-mcp-rate-limit", "Key": {"bucket": {"S": ANY}},
        "UpdateExpression": ANY, "ConditionExpression": ANY, "ExpressionAttributeValues": ANY,
    })
    stub.add_client_error("update_item", service_error_code="ConditionalCheckFailedException", http_status_code=400)
    limiter = DynamoDBRateLimiter("secondchance-demo-mcp-rate-limit", client=client)
    with stub:
        limiter.consume("tenant:subject:knowledge_search", 30)
        with pytest.raises(PolicyDenied, match="rate limit"):
            limiter.consume("tenant:subject:knowledge_search", 30)


def test_executor_invoke_matches_the_lambda_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECONDCHANCE_TOOL_EXECUTOR_URL", raising=False)
    monkeypatch.setenv("SECONDCHANCE_TOOL_EXECUTOR_FUNCTION", "secondchance-demo-tool-executor")
    client = boto3.client("lambda", **FAKE)
    stub = Stubber(client)
    raw = json.dumps({"hits": []}).encode()
    stub.add_response("invoke", {"StatusCode": 200, "Payload": StreamingBody(io.BytesIO(raw), len(raw))},
                      {"FunctionName": "secondchance-demo-tool-executor", "InvocationType": "RequestResponse", "Payload": ANY})
    with stub, patch("boto3.client", return_value=client):
        assert service._invoke_executor({"name": "knowledge_search", "arguments": {}, "context": {}}) == {"hits": []}
