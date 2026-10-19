import json
import logging

from mcp_gateway import service  # at import: it installs the bare-JSON root handler, as on Lambda
from mcp_gateway.policy import MemoryRateLimiter, PolicyDenied, ToolPolicy


def test_policy_rejects_unknown_tool_and_unapproved_agent() -> None:
    policy = ToolPolicy()
    try:
        policy.authorize("shell", "knowledge_research", "coordinator", {})
    except PolicyDenied:
        pass
    else:
        raise AssertionError("unknown tool was accepted")

    try:
        policy.authorize("knowledge_search", "request_analysis", "coordinator", {"query": "food"})
    except PolicyDenied:
        pass
    else:
        raise AssertionError("unapproved agent was accepted")


def test_policy_allows_rag_only_for_declared_evidence_using_specialists() -> None:
    policy = ToolPolicy()

    for agent in ("donation_operations", "logistics_planning", "knowledge_research", "compliance_review"):
        assert policy.authorize("knowledge_search", agent, "coordinator", {"query": "cold chain"}) == {
            "query": "cold chain", "top_k": 6,
        }


def test_rate_limit_is_scoped_by_tenant_subject_and_tool() -> None:
    limiter = MemoryRateLimiter(limit=2, window_seconds=60)
    key = "tenant:user:knowledge_search"
    limiter.consume(key)
    limiter.consume(key)
    try:
        limiter.consume(key)
    except PolicyDenied as exc:
        assert "rate limit" in str(exc)
    else:
        raise AssertionError("rate limit was not enforced")
    limiter.consume("other:user:knowledge_search")


def test_denials_are_bare_json_lines_for_the_cloudwatch_metric_filter(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        result = service.handle({
            "name": "knowledge_search", "arguments": {"query": "cold chain"},
            "context": {"agent": "intruder", "role": "coordinator", "tenant_id": "t", "subject": "s", "correlation_id": "c"},
        })

    assert result["status_code"] == 403
    assert service._handler in logging.getLogger().handlers
    event = json.loads(service._handler.format(caplog.records[-1]))  # what CloudWatch receives
    assert (event["event"], event["outcome"]) == ("tool_call", "denied")
