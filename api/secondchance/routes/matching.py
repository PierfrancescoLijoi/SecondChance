"""Matching runs, pending proposals and their human decision (FR-020, FR-021, FR-022)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance import matching, missions
from secondchance.admission import admit_matching_run
from secondchance.db import tenant_transaction
from secondchance.identity import Claims, MANAGERS, require_roles, tenant_session
from secondchance.notifications import dispatch, notify_queue
from secondchance.observability import current_correlation_id
from secondchance.queues import Queue
from secondchance.routes.knowledge import jobs_queue  # one jobs queue: ingestion and the solver

router = APIRouter(tags=["matching"])
TenantSession = Depends(tenant_session, scope="function")


class MatchingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_limit_seconds: int = Field(default=5, ge=1, le=30)


class MatchingRunCreated(BaseModel):
    id: uuid.UUID
    status: Literal["queued"]


class MatchingRun(BaseModel):
    id: uuid.UUID
    status: str
    solver: str
    time_limit_ms: int
    random_seed: int
    input_sha256: str | None
    objective: Decimal | None
    solver_status: str | None
    stats: dict
    error_category: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class Proposal(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    offer_id: uuid.UUID
    offer_version: int
    center_id: uuid.UUID
    center_name: str
    donor_name: str
    category: str
    storage: str
    date_kind: str
    expires_on: date
    pickup_from: datetime
    pickup_until: datetime
    quantity: Decimal
    unit: str
    load_kg: Decimal
    score: int
    distance_km: Decimal | None
    deliver_after: datetime
    deliver_before: datetime
    explanation: dict
    alternatives: list[dict]
    content_sha256: str
    status: str
    decided_at: datetime | None
    decision_reason: str | None
    created_at: datetime
    # AI Act art. 50 style transparency: this is a machine suggestion awaiting a human decision.
    generated_by: Literal["secondchance-solver"] = "secondchance-solver"


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    volunteer_membership_id: uuid.UUID | None = None
    center_id: uuid.UUID | None = None
    reason: Literal[missions.REJECT_REASONS] | None = None  # type: ignore[valid-type]

    @model_validator(mode="after")
    def coherent(self) -> "ProposalDecision":
        if self.approve and self.volunteer_membership_id is None:
            raise ValueError("an approval assigns a volunteer")
        if not self.approve and (self.volunteer_membership_id or self.center_id):
            raise ValueError("a rejection carries a reason only")
        return self


class DecisionOutcome(BaseModel):
    proposal_id: uuid.UUID
    status: Literal["approved", "rejected"]
    mission_id: uuid.UUID | None


class Volunteer(BaseModel):
    membership_id: uuid.UUID
    display_name: str
    open_missions: int


_RUN = (
    "SELECT id, status, solver, time_limit_ms, random_seed, input_sha256, objective, solver_status, stats,"
    " error_category, created_at, started_at, finished_at FROM matching_run"
)


@router.post("/matching-runs", response_model=MatchingRunCreated, status_code=202)
def post_matching_run(
    body: MatchingRequest,
    claims: Claims = Depends(require_roles(*MANAGERS)),
    queue: Queue = Depends(jobs_queue),
) -> MatchingRunCreated:
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        admit_matching_run(session)  # ADR-016: one run at a time per network, daily quota
        run_id, message = matching.start_run(session, claims, body.time_limit_seconds * 1000, current_correlation_id())
    queue.send(message)  # after the commit; the requeue job re-sends a lost message
    return MatchingRunCreated(id=run_id, status="queued")


@router.get("/matching-runs", response_model=list[MatchingRun])
def get_matching_runs(session: Session = TenantSession, _: Claims = Depends(require_roles(*MANAGERS))) -> list[dict]:
    return [dict(r) for r in session.execute(text(_RUN + " ORDER BY created_at DESC, id LIMIT 20")).mappings()]


@router.get("/matching-runs/{run_id}", response_model=MatchingRun)
def get_matching_run(
    run_id: uuid.UUID, session: Session = TenantSession, _: Claims = Depends(require_roles(*MANAGERS))
) -> dict:
    row = session.execute(text(_RUN + " WHERE id = :id"), {"id": run_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "matching run not found")
    return dict(row)


@router.get("/proposals", response_model=list[Proposal])
def get_proposals(
    status: Literal["proposed", "approved", "rejected", "superseded", "expired"] = "proposed",
    session: Session = TenantSession,
    _: Claims = Depends(require_roles(*MANAGERS)),
) -> list[dict]:
    return missions.list_proposals(session, status)


@router.post("/proposals/{proposal_id}/decision", response_model=DecisionOutcome)
def post_proposal_decision(
    proposal_id: uuid.UUID,
    body: ProposalDecision,
    claims: Claims = Depends(require_roles(*MANAGERS)),
    queue: Queue = Depends(notify_queue),
) -> DecisionOutcome:
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        outcome, emails = missions.decide_proposal(session, claims, proposal_id, body.model_dump(),
                                                   current_correlation_id())
    dispatch(claims.tenant_id, emails, queue)  # the volunteer's email leaves only after the commit (FR-026)
    return DecisionOutcome(**outcome)


@router.get("/volunteers", response_model=list[Volunteer])
def get_volunteers(session: Session = TenantSession, _: Claims = Depends(require_roles(*MANAGERS))) -> list[dict]:
    return missions.list_volunteers(session)
