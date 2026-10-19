"""One natural-language entry point (ADR-015): the intent picks the cheapest path.

Knowledge questions go straight to retrieval, operations to the deterministic API,
complex tasks to an agent run; vague or out-of-scope requests stop here, before any
model or agent is involved (ADR-016, stage 7).
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from secondchance.db import tenant_transaction
from secondchance.identity import CAPABILITIES, Claims, current_claims
from secondchance.knowledge.retrieval import answer
from secondchance.observability import current_correlation_id
from secondchance.queues import Queue
from secondchance.routes.agents import agents_queue, start_agent_run
from secondchance.routes.knowledge import AnswerView, SearchHit
from secondchance.routing import configured_router, record

router = APIRouter(tags=["assist"])

NAVIGATION = {"donation_offer": "/offers", "center_update": "/center", "mission_update": "/missions"}
FORECAST_WORDS = ("prevedi", "previsione", "forecast", "prognose", "prognoz")  # FL-03: after the pilot


class AssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=2, max_length=2000)


class AssistResponse(BaseModel):
    request_id: uuid.UUID
    intent: str
    kind: Literal["answer", "navigate", "agent_run", "clarify", "unsupported", "unavailable", "not_allowed"]
    message: str | None = None
    target: str | None = None
    run_id: uuid.UUID | None = None
    answer: AnswerView | None = None


@router.post("/assist", response_model=AssistResponse)
def post_assist(
    body: AssistRequest, claims: Claims = Depends(current_claims), queue: Queue = Depends(agents_queue)
) -> AssistResponse:
    request_id, cid = uuid.uuid4(), current_correlation_id()
    decision = configured_router().route(body.message)
    intent = decision.intent or "CLARIFICATION"
    capabilities = CAPABILITIES[claims.role]
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        record(session, request_id, decision, shadow=False, correlation_id=cid)
        if intent == "KNOWLEDGE_QUERY" and "knowledge.search" in capabilities:
            result = answer(session, body.message)
            view = AnswerView(answer=result.text, abstained=result.abstained, reason=result.reason, mode=result.mode,
                              sources=[SearchHit.of(h) for h in result.sources], cited=result.cited,
                              model_id=result.model_id)
            return AssistResponse(request_id=request_id, intent=intent, kind="answer", answer=view)

    if intent == "MULTI_AGENT_TASK":
        if "agents.run" not in capabilities:
            return AssistResponse(request_id=request_id, intent=intent, kind="not_allowed",
                                  message="Multi-step planning is available to coordinators and admins.")
        run_id = start_agent_run(claims, body.message, queue)
        return AssistResponse(request_id=request_id, intent=intent, kind="agent_run", run_id=run_id)
    if intent == "DIRECT_OPERATION":
        return AssistResponse(request_id=request_id, intent=intent, kind="navigate",
                              target=NAVIGATION.get(decision.route or "", "/offers"))
    if intent == "SINGLE_CAPABILITY":
        if any(word in body.message.lower() for word in FORECAST_WORDS):
            return AssistResponse(request_id=request_id, intent=intent, kind="unavailable",
                                  message="Demand forecasting arrives after the pilot, on real history (FL-03).")
        if "matching.run" not in capabilities:
            return AssistResponse(request_id=request_id, intent=intent, kind="not_allowed",
                                  message="Allocation optimisation is available to coordinators and admins.")
        # The solver only proposes: the matching screen is where a person reviews and approves (FR-022).
        return AssistResponse(request_id=request_id, intent=intent, kind="navigate", target="/matching")
    if intent == "UNSUPPORTED":
        return AssistResponse(request_id=request_id, intent=intent, kind="unsupported",
                              message="SecondChance does not handle payments, medical or legal advice, or decisions about people.")
    return AssistResponse(request_id=request_id, intent=intent, kind="clarify",
                          message="Can you say what you need: a question about procedures, an offer, or a plan?")
