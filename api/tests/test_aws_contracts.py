"""Every AWS call the application makes, checked against botocore's service models (the API
definitions AWS publishes): real boto3 clients with a Stubber, so an invalid parameter or a
response field we read but AWS never returns fails here, not on the first deploy. No network."""

import io
import json
import uuid
from unittest.mock import patch

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from secondchance import storage
from secondchance.knowledge.embeddings import DIMENSIONS, BedrockTitanEmbedding
from secondchance.llm import BedrockClaude, Guardrail
from secondchance.queues import SqsQueue
from secondchance.tools.client import ToolGatewayClient, ToolInvocation

FAKE = {"region_name": "eu-central-1", "aws_access_key_id": "test", "aws_secret_access_key": "test"}


def stubbed(service: str):
    client = boto3.client(service, **FAKE)
    return client, Stubber(client)


def body(payload: dict) -> StreamingBody:
    raw = json.dumps(payload).encode()
    return StreamingBody(io.BytesIO(raw), len(raw))


def test_converse_request_and_response_match_the_bedrock_runtime_model() -> None:
    client, stub = stubbed("bedrock-runtime")
    stub.add_response("converse", {
        "output": {"message": {"role": "assistant", "content": [{"text": "OK"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 1, "totalTokens": 13},
        "metrics": {"latencyMs": 80},
    })
    with stub, patch("boto3.client", return_value=client):
        completion = BedrockClaude("eu.amazon.nova-lite-v1:0").complete("system prompt", "question")
    assert (completion.text, completion.input_tokens, completion.refused) == ("OK", 12, False)


def test_apply_guardrail_with_grounding_qualifiers_matches_the_model() -> None:
    client, stub = stubbed("bedrock-runtime")
    usage = {"topicPolicyUnits": 0, "contentPolicyUnits": 1, "wordPolicyUnits": 0, "sensitiveInformationPolicyUnits": 1,
             "sensitiveInformationPolicyFreeUnits": 0, "contextualGroundingPolicyUnits": 1}
    for action in ("NONE", "GUARDRAIL_INTERVENED"):
        stub.add_response("apply_guardrail", {"usage": usage, "action": action, "outputs": [], "assessments": []})
    with stub, patch("boto3.client", return_value=client):
        guard = Guardrail("abcd1234efgh", "1")
        assert guard.blocks_question("At which temperature must yogurt be kept?") is False
        assert guard.blocks_answer("question", ["source one"], "answer") is True


def test_titan_embedding_request_matches_the_model() -> None:
    client, stub = stubbed("bedrock-runtime")
    stub.add_response("invoke_model", {"body": body({"embedding": [0.1] * DIMENSIONS}), "contentType": "application/json"})
    with stub, patch("boto3.client", return_value=client):
        vectors = BedrockTitanEmbedding().embed(["cold chain"])
    assert len(vectors[0]) == DIMENSIONS


def test_mcp_gateway_lambda_invoke_matches_the_model() -> None:
    client, stub = stubbed("lambda")
    stub.add_response("invoke", {"StatusCode": 200, "Payload": body({"result": {"hits": []}})},
                      {"FunctionName": "secondchance-demo-mcp-gateway", "InvocationType": "RequestResponse", "Payload": stub_any()})
    invocation = ToolInvocation("knowledge_search", {"query": "x y"}, str(uuid.uuid4()), "s", "coordinator", "knowledge_research", "c")
    with stub:
        result = ToolGatewayClient(function_name="secondchance-demo-mcp-gateway", lambda_client=client).call(invocation)
    assert result == {"hits": []}


def test_sqs_send_receive_delete_match_the_model() -> None:
    client, stub = stubbed("sqs")
    url = "https://sqs.eu-central-1.amazonaws.com/123456789012/secondchance-demo-agents"
    stub.add_response("get_queue_url", {"QueueUrl": url}, {"QueueName": "secondchance-demo-agents"})
    stub.add_response("send_message", {"MessageId": "m-1", "MD5OfMessageBody": "0" * 32})
    stub.add_response("receive_message", {"Messages": [{"MessageId": "m-1", "ReceiptHandle": "r-1", "Body": '{"run_id": "x"}'}]})
    stub.add_response("delete_message", {}, {"QueueUrl": url, "ReceiptHandle": "r-1"})
    with stub:
        queue = SqsQueue("secondchance-demo-agents", client=client)
        queue.send({"run_id": "x", "correlation_id": "c-1"})
        assert queue.receive() == [("r-1", {"run_id": "x"})]
        queue.delete("r-1")


def test_s3_put_and_get_match_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = stubbed("s3")
    tenant = uuid.uuid4()
    monkeypatch.setenv("SECONDCHANCE_S3_BUCKET", "secondchance-demo-objects-123456789012")

    class Session:
        def execute(self, *_):
            return type("Result", (), {"scalar_one_or_none": lambda self: tenant})()

    key = f"tenants/{tenant}/documents/guide.pdf"
    stub.add_response("put_object", {"ETag": '"e"'}, {"Bucket": "secondchance-demo-objects-123456789012", "Key": key,
                                                       "Body": b"%PDF", "ContentType": "application/pdf"})
    stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(b"%PDF"), 4)}, {"Bucket": "secondchance-demo-objects-123456789012", "Key": key})
    with stub:
        assert storage.put(Session(), "documents", "guide.pdf", b"%PDF", "application/pdf", s3=client) == key
        assert storage.get(Session(), "documents", "guide.pdf", s3=client) == b"%PDF"


def test_rds_iam_token_is_signed_offline_for_the_database_user() -> None:
    token = boto3.client("rds", **FAKE).generate_db_auth_token(
        DBHostname="secondchance-demo.cluster-x.eu-central-1.rds.amazonaws.com", Port=5432, DBUsername="secondchance_app"
    )
    assert token.startswith("secondchance-demo.cluster-x.eu-central-1.rds.amazonaws.com:5432/?Action=connect&DBUser=secondchance_app")
    assert "X-Amz-Signature=" in token


def stub_any():
    from botocore.stub import ANY

    return ANY
