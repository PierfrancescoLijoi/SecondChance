"""Governed supervisor planning and reusable specialist-agent factory.

The model may select and order only specialists registered in ``AgentCatalog``. It
cannot create Python code, grant capabilities, select a tenant, or execute writes.
"""

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from secondchance.agents.runtime import Agent, RunContext, StepResult
from secondchance.llm import Completion, Model, model
from secondchance.memory import recall

MAX_PLAN_STEPS = 4
NAME = re.compile(r"^[a-z][a-z0-9_]{2,48}$")
PLAN_PREFIX = "plan:"
RESULT_PREFIX = "result:"
ALLOWED_RESOURCES = frozenset({"run_memory", "knowledge_index", "bedrock", "routing_context"})
ALLOWED_TOOLS = frozenset({"knowledge_search"})
TOOL_RESOURCES = {"knowledge_search": "knowledge_index"}
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanStep:
    agent: str
    objective: str


@dataclass(frozen=True)
class Synthesis:
    summary: str
    risks: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    recommended_next_action: str

    def as_text(self) -> str:
        parts = [self.summary, f"Recommended next action: {self.recommended_next_action}"]
        if self.risks:
            parts.append("Risks: " + "; ".join(self.risks))
        if self.evidence_gaps:
            parts.append("Evidence gaps: " + "; ".join(self.evidence_gaps))
        return " ".join(parts)


@dataclass(frozen=True)
class Specialist:
    name: str
    description: str
    instructions: str
    resources: tuple[str, ...] = ("run_memory", "bedrock")
    tools: tuple[str, ...] = ()

    def build(self) -> Agent:
        prompt_hash = hashlib.sha256(self.instructions.encode()).hexdigest()

        def run(context: RunContext) -> StepResult:
            with context.transaction() as session:
                task = recall(session, scope="run", run_id=context.run_id, kinds=("task",), limit=1)
                findings = recall(session, scope="run", run_id=context.run_id, kinds=("finding",), limit=20)
            if not task:
                return StepResult(outcome="failed", error_category="missing_task")
            objective = _objective_for(self.name, findings)
            previous = [f.content for f in reversed(findings) if f.content.startswith(RESULT_PREFIX)]
            tool_results = []
            if self.tools:
                from secondchance.tools.client import ToolGatewayClient, ToolInvocation

                try:
                    gateway = ToolGatewayClient.from_environment()
                    tool_results = [gateway.call(ToolInvocation(
                        name=name, arguments={"query": objective}, tenant_id=str(context.tenant_id),
                        subject=context.subject, role=context.role, agent=self.name,
                        correlation_id=context.correlation_id, run_id=str(context.run_id), seq=context.seq,
                    )) for name in self.tools]
                except Exception:  # noqa: BLE001 - explicit resilience boundary for an external service
                    log.exception("specialist tool gateway unavailable", extra={"agent": self.name})
                    tool_results = [{"error": "authorised_evidence_unavailable", "hits": []}]
            llm = model()
            if llm is None:
                degraded = any(item.get("error") for item in tool_results)
                result = (
                    f"{self.description}: reviewed '{objective}' using deterministic local mode"
                    f" with {sum(len(item.get('hits', [])) for item in tool_results)} authorised sources."
                    + (" Authorised evidence was unavailable; operator verification is required." if degraded else "")
                )
                return StepResult(
                    outcome="continue", next_agent="supervisor", memories=(("finding", f"result:{self.name}:{result}"),)
                )
            user = json.dumps(
                {
                    "task": task[0].content, "objective": objective,
                    "previous_findings": previous, "authorised_tool_results": tool_results,
                },
                ensure_ascii=False,
            )
            completion = llm.complete(
                self.instructions
                + "\nReturn analysis and a proposed next action only. Never claim that an operation was executed.",
                user,
            )
            if completion.refused:
                return StepResult(outcome="failed", error_category="model_refused")
            return StepResult(
                outcome="continue",
                next_agent="supervisor",
                memories=(("finding", f"result:{self.name}:{completion.text}"),),
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                model_id=llm.model_id,
                prompt_sha256=prompt_hash,
            )

        return run


class AgentCatalog:
    def __init__(self, version: str = "in-memory") -> None:
        self.version = version
        self._specialists: dict[str, Specialist] = {}

    def register(self, specialist: Specialist) -> None:
        if specialist.name in self._specialists:
            raise ValueError(f"specialist {specialist.name!r} already registered")
        self._specialists[specialist.name] = specialist

    def __contains__(self, name: str) -> bool:
        return name in self._specialists

    def descriptions(self) -> dict[str, str]:
        return {name: item.description for name, item in self._specialists.items()}

    def agents(self) -> Mapping[str, Agent]:
        return {name: specialist.build() for name, specialist in self._specialists.items()}

    def tool_callers(self, tool: str) -> frozenset[str]:
        """Specialists that declare ``tool``: the executor's allow-list, so the two never drift."""
        return frozenset(name for name, item in self._specialists.items() if tool in item.tools)

    def manifest(self) -> list[dict[str, object]]:
        """Public, serialisable governance contract for operators and deployment checks."""
        return [
            {
                "name": item.name,
                "role": item.description,
                "resources": list(item.resources),
                "execution": "read_only_analysis",
                "human_approval_for_writes": True,
                "tools": list(item.tools),
            }
            for item in self._specialists.values()
        ]


def create_specialist(
    name: str,
    description: str,
    instructions: str,
    *,
    resources: tuple[str, ...] = ("run_memory", "bedrock"),
    tools: tuple[str, ...] = (),
) -> Specialist:
    """Create a specialist definition; registering it makes it available to the supervisor."""
    if not NAME.fullmatch(name):
        raise ValueError("specialist name must be a safe snake_case identifier")
    if not description.strip() or not instructions.strip():
        raise ValueError("specialist description and instructions are required")
    if len(set(resources)) != len(resources) or any(resource not in ALLOWED_RESOURCES for resource in resources):
        raise ValueError("specialist resource must be unique and allow-listed")
    if len(set(tools)) != len(tools) or any(tool not in ALLOWED_TOOLS for tool in tools):
        raise ValueError("specialist tool must be unique and allow-listed")
    for tool in tools:
        required = TOOL_RESOURCES[tool]
        if required not in resources:
            raise ValueError(f"tool {tool!r} requires declared resource {required!r}")
    return Specialist(name, description.strip(), instructions.strip(), resources, tools)


def load_catalog(path: str | Path | None = None) -> AgentCatalog:
    """Load and validate the versioned, operator-editable specialist contract."""
    catalog_path = Path(path) if path else Path(__file__).with_name("specialists.v1.json")
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        if set(payload) != {"schema_version", "catalog_version", "specialists"}:
            raise ValueError("catalog has unexpected fields")
        if payload["schema_version"] != 1 or not isinstance(payload["catalog_version"], str):
            raise ValueError("unsupported specialist catalog schema")
        rows = payload["specialists"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("specialist catalog must not be empty")
        catalog = AgentCatalog(payload["catalog_version"])
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "name", "description", "instructions", "resources", "tools",
            }:
                raise ValueError("invalid specialist catalog entry")
            catalog.register(create_specialist(
                row["name"], row["description"], row["instructions"],
                resources=tuple(row["resources"]), tools=tuple(row["tools"]),
            ))
        return catalog
    except (OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid specialist catalog: {exc}") from exc


FALLBACK_PLANS: dict[str, tuple[str, ...]] = {
    "donation_offer": ("donation_operations", "compliance_review"),
    "center_update": ("logistics_planning", "compliance_review"),
    "mission_update": ("logistics_planning", "compliance_review"),
}


def plan_operations(
    task: str, route: str, catalog: AgentCatalog, planner: Model | None = None
) -> tuple[tuple[PlanStep, ...], Completion | None]:
    planner = planner if planner is not None else model()
    completion = None
    if planner is not None:
        system = (
            "You are the SecondChance supervisor. Build a short plan using only the approved specialist catalog. "
            "Return strict JSON as {\"steps\":[{\"agent\":\"name\",\"objective\":\"specific read-only objective\"}]}. "
            "Do not invent agents, tools, permissions or write operations. Approved specialist catalog: "
            + json.dumps(catalog.descriptions(), ensure_ascii=False)
        )
        completion = planner.complete(system, json.dumps({"task": task, "route": route}, ensure_ascii=False))
        if not completion.refused:
            parsed = _parse_plan(completion.text, catalog)
            if parsed:
                return parsed, completion
    names = [name for name in FALLBACK_PLANS.get(route, ("request_analysis", "compliance_review")) if name in catalog]
    return tuple(PlanStep(name, catalog.descriptions()[name]) for name in names), completion


def synthesize_results(
    task: str,
    route: str,
    results: list[str],
    synthesizer: Model | None = None,
) -> tuple[Synthesis, Completion | None]:
    """Create a bounded decision-support result; never represent a proposed action as executed."""
    fallback = Synthesis(
        summary=" ".join(results) or f"Request analysed for the {route} workflow.",
        risks=(),
        evidence_gaps=("Model synthesis was unavailable or invalid.",),
        recommended_next_action="Ask an authorised operator to review the findings before any action.",
    )
    synthesizer = synthesizer if synthesizer is not None else model()
    if synthesizer is None:
        return fallback, None
    system = (
        "Synthesize specialist findings for decision support. Return strict JSON only with exactly: "
        '{"summary":"...","risks":["..."],"evidence_gaps":["..."],'
        '"recommended_next_action":"..."}. Use only supplied findings, never claim an action was executed, '
        "and require human approval for operational writes. Use at most five risks and five evidence gaps."
    )
    completion = synthesizer.complete(
        system,
        json.dumps({"task": task, "route": route, "specialist_results": results}, ensure_ascii=False),
    )
    if completion.refused:
        return fallback, completion
    try:
        payload = json.loads(completion.text)
        if not isinstance(payload, dict) or set(payload) != {
            "summary", "risks", "evidence_gaps", "recommended_next_action",
        }:
            raise ValueError("invalid synthesis schema")
        summary = _bounded_text(payload["summary"], 20, 2000)
        action = _bounded_text(payload["recommended_next_action"], 10, 500)
        risks = _bounded_list(payload["risks"])
        gaps = _bounded_list(payload["evidence_gaps"])
        return Synthesis(summary, risks, gaps, action), completion
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback, completion


def encode_plan(steps: tuple[PlanStep, ...]) -> str:
    return PLAN_PREFIX + json.dumps(
        {"steps": [{"agent": step.agent, "objective": step.objective} for step in steps]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_plan(content: str) -> tuple[PlanStep, ...]:
    payload = json.loads(content.removeprefix(PLAN_PREFIX))
    return tuple(PlanStep(step["agent"], step["objective"]) for step in payload["steps"])


def _parse_plan(raw: str, catalog: AgentCatalog) -> tuple[PlanStep, ...] | None:
    try:
        payload = json.loads(raw)
        rows = payload["steps"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_PLAN_STEPS:
            return None
        steps = tuple(PlanStep(row["agent"], row["objective"].strip()) for row in rows)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if len({step.agent for step in steps}) != len(steps):
        return None
    if any(step.agent not in catalog or not 3 <= len(step.objective) <= 240 for step in steps):
        return None
    return steps


def _objective_for(name: str, findings) -> str:
    plan_memory = next((f.content for f in findings if f.content.startswith(PLAN_PREFIX)), None)
    if plan_memory:
        for step in decode_plan(plan_memory):
            if step.agent == name:
                return step.objective
    return "Analyse the request within your approved specialty"


def _bounded_text(value: object, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError("invalid synthesis text")
    return value.strip()


def _bounded_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError("invalid synthesis list")
    return tuple(_bounded_text(item, 3, 300) for item in value)
