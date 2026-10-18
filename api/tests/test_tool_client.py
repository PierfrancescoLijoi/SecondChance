import json
from unittest.mock import Mock

from secondchance.tools.client import ToolGatewayClient, ToolInvocation


def test_lambda_transport_sends_only_governed_invocation() -> None:
    lambda_client = Mock()
    lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "Payload": Mock(read=lambda: json.dumps({"result": {"hits": []}}).encode()),
    }
    client = ToolGatewayClient(function_name="secondchance-mcp-gateway", lambda_client=lambda_client)

    result = client.call(ToolInvocation(
        name="knowledge_search", arguments={"query": "food safety"},
        tenant_id="00000000-0000-0000-0000-000000000001", subject="user-1",
        role="coordinator", agent="knowledge_research", correlation_id="trace-1",
    ))

    assert result == {"hits": []}
    request = json.loads(lambda_client.invoke.call_args.kwargs["Payload"])
    assert request["name"] == "knowledge_search"
    assert request["context"]["agent"] == "knowledge_research"
    assert lambda_client.invoke.call_args.kwargs["InvocationType"] == "RequestResponse"


def test_gateway_failure_is_not_silently_converted_to_empty_results() -> None:
    lambda_client = Mock()
    lambda_client.invoke.return_value = {
        "StatusCode": 200,
        "FunctionError": "Unhandled",
        "Payload": Mock(read=lambda: b'{"errorMessage":"rate limited"}'),
    }
    client = ToolGatewayClient(function_name="gateway", lambda_client=lambda_client)

    try:
        client.call(ToolInvocation(
            name="knowledge_search", arguments={"query": "x"}, tenant_id="tenant",
            subject="subject", role="coordinator", agent="knowledge_research", correlation_id="cid",
        ))
    except RuntimeError as exc:
        assert "rate limited" in str(exc)
    else:
        raise AssertionError("gateway error must propagate")
