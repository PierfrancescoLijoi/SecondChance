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


def test_s3_scan_verdict_is_the_guardduty_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = stubbed("s3")
    monkeypatch.setenv("SECONDCHANCE_S3_BUCKET", "secondchance-demo-objects-123456789012")
    key = "tenants/t/documents/guide.pdf"
    expected = {"Bucket": "secondchance-demo-objects-123456789012", "Key": key}
    stub.add_response("get_object_tagging", {"TagSet": [{"Key": "GuardDutyMalwareScanStatus", "Value": "NO_THREATS_FOUND"}]}, expected)
    stub.add_response("get_object_tagging", {"TagSet": []}, expected)
    with stub:
        assert storage.scan_status(key, s3=client) == "NO_THREATS_FOUND"
        assert storage.scan_status(key, s3=client) is None  # scan still running


def test_rds_iam_token_is_signed_offline_for_the_database_user() -> None:
    token = boto3.client("rds", **FAKE).generate_db_auth_token(
        DBHostname="secondchance-demo.cluster-x.eu-central-1.rds.amazonaws.com", Port=5432, DBUsername="secondchance_app"
    )
    assert token.startswith("secondchance-demo.cluster-x.eu-central-1.rds.amazonaws.com:5432/?Action=connect&DBUser=secondchance_app")
    assert "X-Amz-Signature=" in token


def stub_any():
    from botocore.stub import ANY

    return ANY


def test_cognito_lookup_by_sub_matches_the_model() -> None:
    from secondchance.notify import CognitoDirectory

    client, stub = stubbed("cognito-idp")
    pool = "eu-central-1_AbCdEfGhI"
    expected = {"UserPoolId": pool, "Filter": 'sub = "0b5c5c1e-2f1e-4a7e-9d2c-1f2e3d4c5b6a"', "Limit": 1,
                "AttributesToGet": ["email", "email_verified"]}
    stub.add_response("list_users", {"Users": [{"Username": "0b5c5c1e-2f1e-4a7e-9d2c-1f2e3d4c5b6a", "Enabled": True,
                                                "Attributes": [{"Name": "email", "Value": "v@example.org"},
                                                               {"Name": "email_verified", "Value": "true"}]}]}, expected)
    stub.add_response("list_users", {"Users": []}, expected)
    with stub:
        directory = CognitoDirectory(pool, client=client)
        assert directory.email_for("0b5c5c1e-2f1e-4a7e-9d2c-1f2e3d4c5b6a") == "v@example.org"
        assert directory.email_for("0b5c5c1e-2f1e-4a7e-9d2c-1f2e3d4c5b6a") is None


def test_ses_send_email_matches_the_model_and_maps_permanent_refusals() -> None:
    from secondchance.notify import PermanentFailure, SesMailer

    client, stub = stubbed("sesv2")
    stub.add_response("send_email", {"MessageId": "m-1"}, {
        "FromEmailAddress": "SecondChance <alerts@example.org>", "Destination": {"ToAddresses": ["v@example.org"]},
        "Content": {"Simple": {"Subject": {"Data": "s", "Charset": "UTF-8"},
                               "Body": {"Text": {"Data": "b", "Charset": "UTF-8"}}}},
    })
    stub.add_client_error("send_email", service_error_code="MessageRejected",
                          service_message="Email address is not verified.", http_status_code=400)
    stub.add_client_error("send_email", service_error_code="TooManyRequestsException", http_status_code=429)
    with stub:
        mailer = SesMailer("SecondChance <alerts@example.org>", client=client)
        mailer.send("v@example.org", "s", "b")
        with pytest.raises(PermanentFailure):
            mailer.send("v@example.org", "s", "b")
        with pytest.raises(Exception, match="TooManyRequests"):
            mailer.send("v@example.org", "s", "b")


def test_step_functions_and_sqs_messages_for_matching_carry_identifiers_only() -> None:
    from secondchance.matching import job_message
    from secondchance.notifications import message

    tenant, run = uuid.uuid4(), uuid.uuid4()
    assert set(job_message(tenant, run, "c")) == {"type", "tenant_id", "run_id", "correlation_id"}
    assert set(message(tenant, run, "sub", "mission_assigned", "en", "c")) == {
        "type", "tenant_id", "delivery_id", "recipient", "kind", "language", "correlation_id"}
