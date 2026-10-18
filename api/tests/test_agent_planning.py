import json

import pytest

from secondchance.agents.planning import (
    AgentCatalog,
    PlanStep,
    create_specialist,
    load_catalog,
    plan_operations,
    synthesize_results,
)
from secondchance.llm import Completion


class FakeModel:
    model_id = "fake-planner"

    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, system: str, user: str) -> Completion:
        assert "approved specialist catalog" in system
        assert "donation_offer" in user
        return Completion(self.response, input_tokens=20, output_tokens=8)


def test_supervisor_accepts_only_a_valid_allowlisted_plan() -> None:
    catalog = AgentCatalog()
    catalog.register(create_specialist("donation_operations", "Validates donations", "Read-only analysis."))
    catalog.register(create_specialist("compliance_review", "Checks constraints", "Review only."))
    response = json.dumps(
        {
            "steps": [
                {"agent": "donation_operations", "objective": "Validate the offered food"},
                {"agent": "compliance_review", "objective": "Review the proposed handling"},
            ]
        }
    )

    plan, completion = plan_operations("Donate pasta", "donation_offer", catalog, FakeModel(response))

    assert plan == (
        PlanStep("donation_operations", "Validate the offered food"),
        PlanStep("compliance_review", "Review the proposed handling"),
    )
    assert completion is not None and completion.output_tokens == 8


@pytest.mark.parametrize(
    "response",
    [
        '{"steps":[{"agent":"shell","objective":"run arbitrary code"}]}',
        '{"steps":[]}',
        "not json",
    ],
)
def test_invalid_model_plan_falls_back_to_safe_route_plan(response: str) -> None:
    catalog = AgentCatalog()
    catalog.register(create_specialist("donation_operations", "Validates donations", "Read-only analysis."))
    catalog.register(create_specialist("compliance_review", "Checks constraints", "Review only."))

    plan, _ = plan_operations("Donate pasta", "donation_offer", catalog, FakeModel(response))

    assert [step.agent for step in plan] == ["donation_operations", "compliance_review"]


def test_catalog_rejects_duplicate_or_unsafe_specialist_names() -> None:
    catalog = AgentCatalog()
    specialist = create_specialist("knowledge_research", "Finds evidence", "Cite sources.")
    catalog.register(specialist)

    with pytest.raises(ValueError, match="already registered"):
        catalog.register(specialist)
    with pytest.raises(ValueError, match="name"):
        create_specialist("../../unsafe", "Bad", "Bad")


def test_catalog_builds_an_executable_agent_for_every_specialist() -> None:
    catalog = AgentCatalog()
    catalog.register(create_specialist("logistics_planning", "Plans movements", "Never execute writes."))

    agents = catalog.agents()

    assert set(agents) == {"logistics_planning"}
    assert callable(agents["logistics_planning"])


def test_catalog_exposes_roles_and_declared_shared_resources() -> None:
    catalog = AgentCatalog()
    catalog.register(create_specialist(
        "knowledge_research",
        "Finds authorised evidence",
        "Cite sources and abstain when evidence is missing.",
        resources=("run_memory", "knowledge_index", "bedrock"),
    ))

    manifest = catalog.manifest()

    assert manifest == [{
        "name": "knowledge_research",
        "role": "Finds authorised evidence",
        "resources": ["run_memory", "knowledge_index", "bedrock"],
        "execution": "read_only_analysis",
        "human_approval_for_writes": True,
        "tools": [],
    }]


def test_specialist_rejects_unknown_or_duplicate_resources() -> None:
    with pytest.raises(ValueError, match="resource"):
        create_specialist("bad_resources", "Bad", "Bad", resources=("shell",))
    with pytest.raises(ValueError, match="resource"):
        create_specialist("duplicate_resources", "Bad", "Bad", resources=("bedrock", "bedrock"))


def test_specialist_declares_only_allowlisted_tools() -> None:
    specialist = create_specialist(
        "knowledge_research", "Research", "Use evidence.",
        resources=("run_memory", "knowledge_index"), tools=("knowledge_search",),
    )
    assert specialist.tools == ("knowledge_search",)
    with pytest.raises(ValueError, match="tool"):
        create_specialist("unsafe_tool", "Bad", "Bad", tools=("shell",))


def test_tool_capability_requires_its_declared_shared_resource() -> None:
    with pytest.raises(ValueError, match="knowledge_index"):
        create_specialist(
            "knowledge_research", "Research", "Use evidence.",
            resources=("run_memory", "bedrock"), tools=("knowledge_search",),
        )


def test_loads_a_versioned_catalog_from_configuration(tmp_path) -> None:
    path = tmp_path / "specialists.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "catalog_version": "test-2026-10",
        "specialists": [{
            "name": "knowledge_research",
            "description": "Finds authorised evidence",
            "instructions": "Cite supplied evidence only.",
            "resources": ["run_memory", "knowledge_index", "bedrock"],
            "tools": ["knowledge_search"],
        }],
    }), encoding="utf-8")

    catalog = load_catalog(path)

    assert catalog.version == "test-2026-10"
    assert catalog.manifest()[0]["tools"] == ["knowledge_search"]


class _SynthesisModel:
    model_id = "fake-synthesizer"

    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, system: str, user: str) -> Completion:
        assert "strict JSON" in system and "evidence_gaps" in system
        assert json.loads(user)["specialist_results"]
        return Completion(self.response, input_tokens=12, output_tokens=9)


def test_supervisor_synthesis_is_structured_and_schema_validated() -> None:
    raw = json.dumps({
        "summary": "The pickup is feasible after verification.",
        "risks": ["Cold-chain evidence is incomplete"],
        "evidence_gaps": ["Receiving-center capacity"],
        "recommended_next_action": "Ask an operator to verify capacity.",
    })

    synthesis, completion = synthesize_results(
        "Coordinate pickup", "mission_update", ["Logistics reviewed timing"], _SynthesisModel(raw)
    )

    assert synthesis.summary.startswith("The pickup")
    assert synthesis.evidence_gaps == ("Receiving-center capacity",)
    assert completion is not None and completion.output_tokens == 9


def test_invalid_synthesis_falls_back_without_claiming_execution() -> None:
    synthesis, _ = synthesize_results(
        "Coordinate pickup", "mission_update", ["Logistics reviewed timing"], _SynthesisModel("not json")
    )

    assert "Logistics reviewed timing" in synthesis.summary
    assert "operator" in synthesis.recommended_next_action.lower()
