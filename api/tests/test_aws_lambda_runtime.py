from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from secondchance import db, llm, routing
from secondchance.aws_lambda import agent_step, runtime_check
from secondchance.knowledge import embeddings
from secondchance.routing import RouteDecision


def test_runtime_check_exercises_database_models_guardrail_and_router(monkeypatch) -> None:
    connection = Mock()
    connection.execute.return_value.scalar_one.return_value = 1
    monkeypatch.setattr(db.engine, "connect", lambda: nullcontext(connection))

    language_model = Mock()
    language_model.model_id = "eu.anthropic.claude-haiku-5-5"
    language_model.complete.return_value = llm.Completion("OK", 2, 1)
    monkeypatch.setattr(llm, "model", lambda: language_model)

    guard = Mock()
    guard.blocks_question.return_value = False
    monkeypatch.setattr(llm, "guardrail", lambda: guard)

    embedder = Mock()
    embedder.model = "amazon.titan-embed-text-v2:0"
    embedder.embed.return_value = [[0.0] * embeddings.DIMENSIONS]
    monkeypatch.setattr(embeddings, "provider", lambda: embedder)

    router = Mock()
    router.route.return_value = RouteDecision(
        router="hybrid",
        outcome="ok",
        route="mission_update",
        probability=0.95,
        latency_ms=12,
        intent="MULTI_AGENT_TASK",
    )
    monkeypatch.setattr(routing, "configured_router", lambda: router)

    result = runtime_check({}, SimpleNamespace(aws_request_id="test"))

    assert result == {
        "database": "ok",
        "model": "eu.anthropic.claude-haiku-5-5",
        "guardrail": "ok",
        "embedding_model": "amazon.titan-embed-text-v2:0",
        "embedding_dimensions": 1024,
        "router": "hybrid",
        "router_intent": "MULTI_AGENT_TASK",
        "solver": "ok",
    }
    guard.blocks_question.assert_called_once()

    monkeypatch.setattr(llm, "guardrail", lambda: None)
    with pytest.raises(RuntimeError, match="guardrail is not configured"):
        runtime_check({}, SimpleNamespace(aws_request_id="test"))


@pytest.mark.parametrize(
    ("resume", "expected"),
    [
        ("advance", {"continue": True, "retry": False, "seq": 2, "outcome": "continue"}),
        ("wait", {"continue": False, "retry": True, "seq": 1, "outcome": "waiting_for_lease"}),
    ],
)
def test_agent_step_recovers_when_the_previous_lambda_response_was_lost(monkeypatch, resume, expected) -> None:
    import secondchance.agents.runtime as runtime

    monkeypatch.setattr(runtime, "execute", lambda *_args, **_kwargs: "not_claimable")
    monkeypatch.setattr(runtime, "workflow_resume", lambda *_args: resume)
    event = {
        "tenant_id": "10000000-0000-0000-0000-000000000001",
        "run_id": "20000000-0000-0000-0000-000000000001",
        "seq": 1,
        "correlation_id": "30000000-0000-0000-0000-000000000001",
    }

    result = agent_step(event, SimpleNamespace(aws_request_id="test"))

    assert {key: result[key] for key in expected} == expected
