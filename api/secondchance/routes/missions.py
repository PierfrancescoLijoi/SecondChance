"""Missions: list, detail, transitions, reassignment and centre receipts (FR-023, FR-025, FR-027)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from secondchance import missions
from secondchance.db import tenant_transaction
from secondchance.identity import Claims, MANAGERS, require_roles, tenant_session
from secondchance.notifications import dispatch, notify_queue
from secondchance.observability import current_correlation_id
from secondchance.queues import Queue

router = APIRouter(tags=["missions"])
TenantSession = Depends(tenant_session, scope="function")
IdempotencyKey = Header(default=None, alias="Idempotency-Key", min_length=8, max_length=128)


class MissionEvent(BaseModel):
    from_status: str | None
    to_status: str
    actor_role: str
    reason: str | None
    occurred_at: datetime


class MissionView(BaseModel):
    """Minimal operational details: no beneficiary data, no subjects (FR-026, ADR-014)."""

    id: uuid.UUID
    status: str
    version: int
    offer_id: uuid.UUID
    center_id: uuid.UUID
    center_name: str
    center_address: str | None
    donor_name: str
    donor_latitude: float | None
    donor_longitude: float | None
    category: str
    storage: str
    date_kind: str
    expires_on: date
    quantity: Decimal
    unit: str
    pickup_from: datetime
    pickup_until: datetime
    deliver_after: datetime
    deliver_before: datetime
    reassignments: int
    failure_reason: str | None
    receipt: str | None
    receipt_reason: str | None
    received_quantity: Decimal | None
    volunteer_name: str | None
    assigned_to_me: bool
    created_at: datetime
    updated_at: datetime
    accepted_at: datetime | None
    picked_up_at: datetime | None
    delivered_at: datetime | None
    received_at: datetime | None


class MissionDetail(MissionView):
    events: list[MissionEvent]


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: Literal["accepted", "picked_up", "delivered", "failed", "cancelled"]
    version: int = Field(ge=1)
    reason: Literal[missions.FAILURE_REASONS + missions.CANCEL_REASONS] | None = None  # type: ignore[valid-type]


class ReassignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    volunteer_membership_id: uuid.UUID
    version: int = Field(ge=1)


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["confirmed", "exception"]
    version: int = Field(ge=1)
    received_quantity: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=3)
    reason: Literal[missions.EXCEPTION_REASONS] | None = None  # type: ignore[valid-type]


class MissionChanged(BaseModel):
    id: uuid.UUID
    status: str
    version: int
    replayed: bool = False


def _current(claims: Claims, mission_id: uuid.UUID, replayed: bool = False) -> MissionChanged:
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        mission = missions.get_mission(session, claims, mission_id)
    return MissionChanged(id=mission_id, status=mission["status"], version=mission["version"], replayed=replayed)


@router.get("/missions", response_model=list[MissionView])
def get_missions(
    status: Literal["assigned", "accepted", "picked_up", "delivered", "failed", "cancelled"] | None = Query(default=None),
    session=TenantSession,
    claims: Claims = Depends(require_roles("volunteer", "center_staff", *MANAGERS)),
) -> list[dict]:
    return missions.list_missions(session, claims, status=status)


@router.get("/missions/{mission_id}", response_model=MissionDetail)
def get_mission(
    mission_id: uuid.UUID,
    session=TenantSession,
    claims: Claims = Depends(require_roles("volunteer", "center_staff", *MANAGERS)),
) -> dict:
    return missions.get_mission(session, claims, mission_id)


@router.post("/missions/{mission_id}/transition", response_model=MissionChanged)
def post_transition(
    mission_id: uuid.UUID,
    body: TransitionRequest,
    idempotency_key: str | None = IdempotencyKey,
    claims: Claims = Depends(require_roles("volunteer", *MANAGERS)),
    queue: Queue = Depends(notify_queue),
) -> MissionChanged:
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        result, emails = missions.transition(session, claims, mission_id, body.to, body.version, body.reason,
                                             idempotency_key, current_correlation_id())
    dispatch(claims.tenant_id, emails, queue)  # after the commit (FR-026)
    return _current(claims, mission_id, replayed=result["replayed"])


@router.post("/missions/{mission_id}/reassign", response_model=MissionChanged)
def post_reassign(
    mission_id: uuid.UUID,
    body: ReassignRequest,
    claims: Claims = Depends(require_roles(*MANAGERS)),
    queue: Queue = Depends(notify_queue),
) -> MissionChanged:
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        _, emails = missions.reassign(session, claims, mission_id, body.volunteer_membership_id, body.version,
                                      current_correlation_id())
    dispatch(claims.tenant_id, emails, queue)
    return _current(claims, mission_id)


@router.post("/missions/{mission_id}/receipt", response_model=MissionChanged)
def post_receipt(
    mission_id: uuid.UUID,
    body: ReceiptRequest,
    claims: Claims = Depends(require_roles("center_staff", *MANAGERS)),
) -> MissionChanged:
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        missions.record_receipt(session, claims, mission_id, body.model_dump(), current_correlation_id())
    return _current(claims, mission_id)
