"""The tool executor exactly as AWS runs it (ADR-018): the Lambda handler on a real database,
RLS and the RAG corpus, its result marshalled by the Lambda runtime's own encoder."""

import importlib.util
from pathlib import Path

import pytest
from awslambdaric.lambda_runtime_marshaller import to_json

from secondchance.agents.planning import load_catalog
from secondchance.aws_lambda import tool_executor
from secondchance.knowledge.sample import load_demo_documents
from secondchance.seed import TENANT_IT
from secondchance.tools.builtin import GATEWAY

GATEWAY_POLICY = Path(__file__).resolve().parents[2] / "mcp-gateway" / "mcp_gateway" / "policy.py"


@pytest.fixture(scope="module", autouse=True)
def demo_documents() -> None:
    assert set(load_demo_documents()) == {"published"}


def mcp_event(name: str, arguments: dict) -> dict:
    return {
        "name": name,
        "arguments": arguments,
        "context": {
            "tenant_id": str(TENANT_IT), "subject": "demo-it-coordinator", "role": "coordinator",
            "agent": "mcp_client", "correlation_id": "test-lambda-executor",
        },
    }


def test_knowledge_search_runs_on_postgres_and_marshals_like_lambda() -> None:
    result = tool_executor(
        mcp_event("knowledge_search", {"query": "temperatura alimenti refrigerati", "language": "it", "top_k": 3}), None
    )

    assert result["hits"]
    assert all(isinstance(hit["score"], float) for hit in result["hits"])
    to_json(result)  # what awslambdaric returns to Lambda: a UUID or datetime here would fail the invocation


def test_knowledge_answer_marshals_like_lambda() -> None:
    result = tool_executor(
        mcp_event("knowledge_answer", {"question": "A che temperatura vanno conservati gli alimenti refrigerati?", "language": "it"}),
        None,
    )

    assert result["sources"]
    to_json(result)


def test_executor_gateway_and_catalog_allow_the_same_callers() -> None:
    spec = importlib.util.spec_from_file_location("mcp_gateway_policy", GATEWAY_POLICY)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    executor = {tool["name"]: set(tool["agents"]) for tool in GATEWAY.manifest()}

    assert executor == {name: set(tool["agents"]) for name, tool in policy.TOOLS.items()}
    assert load_catalog().tool_callers("knowledge_search") == executor["knowledge_search"] - {"mcp_client"}
