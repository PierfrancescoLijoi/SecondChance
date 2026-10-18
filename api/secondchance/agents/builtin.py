"""Governed supervisor, deterministic intake and an allow-listed specialist catalog."""

from collections.abc import Mapping

from secondchance.agents.runtime import Agent, RunContext, StepResult
from secondchance.agents.planning import (
    PLAN_PREFIX,
    RESULT_PREFIX,
    decode_plan,
    encode_plan,
    load_catalog,
    plan_operations,
    synthesize_results,
)
from secondchance.llm import model
from secondchance.memory import recall
from secondchance.routing import configured_router, configured_shadow_router, record

ROUTE_FINDING = "route:"


def supervisor(context: RunContext) -> StepResult:
    with context.transaction() as session:
        task = recall(session, scope="run", run_id=context.run_id, kinds=("task",), limit=1)
        findings = recall(session, scope="run", run_id=context.run_id, kinds=("finding",))
    if not task:
        return StepResult(outcome="failed", error_category="missing_task")
    routed = next((f.content for f in findings if f.content.startswith(ROUTE_FINDING)), None)
    if routed is None:
        return StepResult(outcome="continue", next_agent="intake")
    _, route, outcome = routed.split(":", 2)
    if outcome != "ok":
        return StepResult(
            outcome="succeeded",
            memories=(("finding", "summary:Request not classified with confidence: an operator is needed."),),
        )
    plan_memory = next((f.content for f in findings if f.content.startswith(PLAN_PREFIX)), None)
    if plan_memory is None:
        planner = model()
        steps, completion = plan_operations(task[0].content, route, CATALOG, planner)
        if not steps:
            return StepResult(outcome="failed", error_category="empty_plan")
        return StepResult(
            outcome="continue",
            next_agent=steps[0].agent,
            memories=(("finding", encode_plan(steps)),),
            input_tokens=completion.input_tokens if completion else 0,
            output_tokens=completion.output_tokens if completion else 0,
            model_id=planner.model_id if completion and planner else None,
        )
    steps = decode_plan(plan_memory)
    completed = {f.content.split(":", 2)[1] for f in findings if f.content.startswith(RESULT_PREFIX)}
    pending = next((step for step in steps if step.agent not in completed), None)
    if pending:
        return StepResult(outcome="continue", next_agent=pending.agent)
    results = [f.content.split(":", 2)[2] for f in reversed(findings) if f.content.startswith(RESULT_PREFIX)]
    synthesizer = model()
    synthesis, completion = synthesize_results(task[0].content, route, results, synthesizer)
    return StepResult(
        outcome="succeeded",
        memories=(("finding", f"summary:{synthesis.as_text()}"),),
        input_tokens=completion.input_tokens if completion else 0,
        output_tokens=completion.output_tokens if completion else 0,
        model_id=synthesizer.model_id if completion and synthesizer else None,
    )


def intake(context: RunContext) -> StepResult:
    with context.transaction() as session:
        task = recall(session, scope="run", run_id=context.run_id, kinds=("task",), limit=1)
        if not task:
            return StepResult(outcome="failed", error_category="missing_task")
    # Bedrock/Rizzo are external calls: never hold an Aurora transaction while waiting.
    decision = configured_router().route(task[0].content)
    shadow = configured_shadow_router()
    shadow_decision = shadow.route(task[0].content) if shadow else None
    with context.transaction() as session:
        record(session, context.run_id, decision, shadow=False, correlation_id=context.correlation_id)
        if shadow_decision:
            record(session, context.run_id, shadow_decision, shadow=True, correlation_id=context.correlation_id)
    finding = f"{ROUTE_FINDING}{decision.route or 'none'}:{decision.outcome}"
    return StepResult(outcome="continue", next_agent="supervisor", memories=(("finding", finding),))


CATALOG = load_catalog()

AGENTS: Mapping[str, Agent] = {"supervisor": supervisor, "intake": intake, **CATALOG.agents()}
