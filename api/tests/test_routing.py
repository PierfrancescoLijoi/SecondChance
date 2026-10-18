"""FR-030 baseline router and ADR-007 Rizzo Flow shadow, against a stub HTTP server."""

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from sqlalchemy import text

from secondchance.db import tenant_transaction
from secondchance.llm import Completion
from secondchance.routing import HybridRouter, KeywordRouter, RizzoFlowRouter, SemanticRouter, route_with_shadow
from secondchance.seed import TENANT_IT


@pytest.mark.parametrize(
    ("request_text", "route"),
    [
        ("Vorrei donare 40 kg di pasta", "donation_offer"),
        ("We have surplus bread to donate", "donation_offer"),
        ("Vi har overskud af brød", "donation_offer"),
        ("Il centro cambia gli orari di apertura", "center_update"),
        ("Pickup done, delivered to the center", "mission_update"),
        ("Hvordan er reglerne for kølevarer?", "procedure_question"),
        ("Chcemy przekazać nadwyżki pieczywa", "donation_offer"),
        ("Jakie są zasady przyjmowania mrożonek?", "procedure_question"),
    ],
)
def test_baseline_routes_known_requests(request_text: str, route: str) -> None:
    decision = KeywordRouter().route(request_text)
    assert (decision.outcome, decision.route) == ("ok", route)


def test_baseline_escalates_when_it_cannot_tell() -> None:
    assert KeywordRouter().route("buongiorno").outcome == "escalate"


class _SemanticModel:
    model_id = "semantic-test"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete(self, system: str, user: str) -> Completion:
        self.calls += 1
        assert "strict JSON" in system and "MULTI_AGENT_TASK" in system
        assert json.loads(user)["request"]
        return Completion(self.response, input_tokens=10, output_tokens=4)


def test_semantic_router_accepts_only_a_confident_schema_valid_decision() -> None:
    semantic = _SemanticModel(json.dumps({
        "route": "mission_update", "intent": "MULTI_AGENT_TASK", "confidence": 0.91,
    }))

    decision = SemanticRouter(semantic).route("Coordinate a pickup and delivery")

    assert (decision.outcome, decision.route, decision.intent) == ("ok", "mission_update", "MULTI_AGENT_TASK")
    assert decision.router == "bedrock" and decision.model_fingerprint == "semantic-test"


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"route":"invented","intent":"MULTI_AGENT_TASK","confidence":0.99}',
        '{"route":"other","intent":"ROOT_ACCESS","confidence":0.99}',
        '{"route":"other","intent":"MULTI_AGENT_TASK","confidence":0.20}',
    ],
)
def test_semantic_router_rejects_malformed_invented_or_low_confidence_decisions(response: str) -> None:
    decision = SemanticRouter(_SemanticModel(response), threshold=0.75).route("Ambiguous compound request")

    assert decision.outcome in {"error", "escalate"}


def test_hybrid_router_keeps_safety_rules_deterministic() -> None:
    semantic = _SemanticModel(json.dumps({
        "route": "other", "intent": "DIRECT_OPERATION", "confidence": 0.99,
    }))

    decision = HybridRouter(semantic=SemanticRouter(semantic)).route("Fammi un pagamento con bonifico")

    assert decision.intent == "UNSUPPORTED"
    assert semantic.calls == 0


def test_hybrid_router_uses_semantic_model_for_compound_planning() -> None:
    semantic = _SemanticModel(json.dumps({
        "route": "mission_update", "intent": "MULTI_AGENT_TASK", "confidence": 0.94,
    }))

    decision = HybridRouter(semantic=SemanticRouter(semantic)).route(
        "Coordina il ritiro e controlla la procedura della catena del freddo"
    )

    assert (decision.router, decision.route, decision.intent) == ("hybrid", "mission_update", "MULTI_AGENT_TASK")
    assert semantic.calls == 1


def test_hybrid_router_falls_back_safely_when_semantic_model_fails() -> None:
    decision = HybridRouter(semantic=SemanticRouter(_SemanticModel("not json"))).route(
        "Coordina il ritiro e controlla la procedura"
    )

    assert decision.router == "hybrid"
    assert decision.intent == "MULTI_AGENT_TASK"
    assert decision.model_fingerprint == "semantic-test:fallback:error"


def test_baseline_golden_set_meets_the_documented_quality_gate() -> None:
    dataset = json.loads((Path(__file__).parents[1] / "evals" / "router_golden.v1.json").read_text(encoding="utf-8"))
    decisions = [(case, KeywordRouter().route(case["request"])) for case in dataset["cases"]]
    correct = sum(
        decision.intent == case["intent"] and (case["route"] is None or decision.route == case["route"])
        for case, decision in decisions
    )

    assert correct / len(decisions) >= dataset["minimum_accuracy"]
    assert all(decision.intent == "UNSUPPORTED" for case, decision in decisions if case["intent"] == "UNSUPPORTED")


class _Stub(BaseHTTPRequestHandler):
    reply: bytes = b""
    seen: list[dict] = []

    def do_POST(self) -> None:
        _Stub.seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(_Stub.reply)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def rizzo():
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Stub.seen = []
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _answer(status: str, choice: str | None, top: float) -> bytes:
    probabilities = {"donation_offer": top, "other": round(1 - top, 3)}
    return json.dumps(
        {"model": {"id": "rizzo-flow-4b-q8_0", "fingerprint": "abc123"},
         "answers": {"route": {"status": status, "choice": choice, "probabilities": probabilities}}}
    ).encode()


def test_rizzo_flow_request_matches_its_schema(rizzo) -> None:
    _Stub.reply = _answer("ok", "donation_offer", 0.92)
    decision = RizzoFlowRouter(rizzo).route("Vorrei donare pasta")
    [sent] = _Stub.seen
    question = sent["questions"]["route"]
    assert set(sent) == {"state", "questions"}
    assert question["type"] == "choice" and question["policy"]["allow_abstain"] is True
    assert {o["id"] for o in question["options"]} >= {"donation_offer", "other"}
    assert (decision.outcome, decision.route, decision.model_fingerprint) == ("ok", "donation_offer", "abc123")


def test_rizzo_flow_uncertain_answer_escalates_with_best_guess(rizzo) -> None:
    _Stub.reply = _answer("uncertain", None, 0.55)
    decision = RizzoFlowRouter(rizzo).route("boh")
    assert (decision.outcome, decision.route) == ("escalate", "donation_offer")


@pytest.mark.parametrize("reply", [b"not json", b'{"answers": {}}'])
def test_rizzo_flow_malformed_answer_is_an_error(rizzo, reply: bytes) -> None:
    _Stub.reply = reply
    assert RizzoFlowRouter(rizzo).route("x").outcome == "error"


def test_shadow_failure_is_recorded_and_never_raised() -> None:
    request_id = uuid.uuid4()
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        decision = route_with_shadow(
            session, request_id, "Vorrei donare pasta", primary=KeywordRouter(),
            shadow=RizzoFlowRouter("http://127.0.0.1:9", timeout=0.5), correlation_id="shadow-test",
        )
        rows = session.execute(
            text("SELECT router, shadow, outcome FROM routing_decision WHERE request_id = :id ORDER BY router"),
            {"id": request_id},
        ).all()
    assert decision.outcome == "ok"
    assert [tuple(r) for r in rows] == [("baseline", False, "ok"), ("rizzo_flow", True, "error")]


def test_hybrid_decision_is_accepted_by_the_persisted_governance_schema() -> None:
    request_id = uuid.uuid4()
    semantic = SemanticRouter(_SemanticModel(json.dumps({
        "route": "mission_update", "intent": "MULTI_AGENT_TASK", "confidence": 0.93,
    })))
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        decision = route_with_shadow(
            session,
            request_id,
            "Coordina il ritiro e controlla la consegna",
            primary=HybridRouter(semantic),
            shadow=None,
            correlation_id="hybrid-schema-test",
        )
        persisted = session.execute(
            text("SELECT router, route, intent FROM routing_decision WHERE request_id = :id"), {"id": request_id}
        ).one()

    assert tuple(persisted) == ("hybrid", "mission_update", "MULTI_AGENT_TASK")
    assert decision.router == "hybrid"
