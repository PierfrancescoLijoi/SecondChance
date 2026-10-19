import uuid
import pytest
from pydantic import BaseModel, Field

from secondchance.tools.gateway import ToolContext, ToolDenied, ToolGateway, ToolSpec


class Input(BaseModel):
    query: str = Field(min_length=2, max_length=20)


class FakeSession:
    def __init__(self) -> None:
        self.audit = []

    def execute(self, statement, params=None):
        if "INSERT INTO audit_event" in str(statement):
            self.audit.append(params)


def context(session, *, role="coordinator", agent="knowledge_research") -> ToolContext:
    return ToolContext(
        session=session,
        tenant_id=uuid.uuid4(),
        subject="person-1",
        role=role,
        agent=agent,
        correlation_id="corr-1",
    )


def test_gateway_validates_authorises_executes_and_audits() -> None:
    gateway = ToolGateway()
    gateway.register(ToolSpec(
        name="knowledge_search",
        description="Search authorised knowledge",
        input_model=Input,
        roles=frozenset({"coordinator"}),
        agents=frozenset({"knowledge_research"}),
        resource="knowledge_index",
        timeout_ms=2000,
        handler=lambda _, body: {"matches": [body.query]},
    ))
    session = FakeSession()

    result = gateway.call("knowledge_search", {"query": "cold chain"}, context(session))

    assert result == {"matches": ["cold chain"]}
    assert session.audit[0]["action"] == "tool.knowledge_search"
    assert session.audit[0]["outcome"] == "success"


def test_gateway_rejects_unknown_tool_invalid_input_role_and_agent() -> None:
    gateway = ToolGateway()
    gateway.register(ToolSpec(
        name="knowledge_search", description="Search", input_model=Input,
        roles=frozenset({"coordinator"}), agents=frozenset({"knowledge_research"}),
        resource="knowledge_index", timeout_ms=2000, handler=lambda *_: {},
    ))
    session = FakeSession()

    with pytest.raises(ToolDenied, match="unknown"):
        gateway.call("shell", {}, context(session))
    with pytest.raises(ToolDenied, match="role"):
        gateway.call("knowledge_search", {"query": "valid"}, context(session, role="donor"))
    with pytest.raises(ToolDenied, match="agent"):
        gateway.call("knowledge_search", {"query": "valid"}, context(session, agent="logistics_planning"))
    with pytest.raises(ValueError):
        gateway.call("knowledge_search", {"query": "x"}, context(session))


def test_manifest_contains_only_public_contract_not_handler() -> None:
    gateway = ToolGateway()
    gateway.register(ToolSpec(
        name="knowledge_search", description="Search", input_model=Input,
        roles=frozenset({"coordinator"}), agents=frozenset({"knowledge_research"}),
        resource="knowledge_index", timeout_ms=2000, handler=lambda *_: {},
    ))

    manifest = gateway.manifest()

    assert manifest[0]["name"] == "knowledge_search"
    assert manifest[0]["read_only"] is True
    assert "handler" not in manifest[0]


def test_builtin_gateway_exposes_rag_search_as_read_only() -> None:
    from secondchance.tools.builtin import GATEWAY

    item = next(item for item in GATEWAY.manifest() if item["name"] == "knowledge_search")
    assert item["resource"] == "knowledge_index"
    assert item["read_only"] is True
    assert "knowledge_research" in item["agents"]
    assert item["input_schema"]["additionalProperties"] is False
    answer = next(item for item in GATEWAY.manifest() if item["name"] == "knowledge_answer")
    assert answer["read_only"] is True
    assert answer["agents"] == ["mcp_client"]


