"""Registration, the current user, and approvals (ADR-017)."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from secondchance.auth import Identity, current_identity
from secondchance.identity import CAPABILITIES, Claims, memberships, require_roles
from secondchance.observability import current_correlation_id
from secondchance.registration import Registration, decide, network_directory, pending, register

router = APIRouter(tags=["accounts"])


class MembershipView(BaseModel):
    membership_id: uuid.UUID
    tenant_id: uuid.UUID
    network_name: str | None
    role: str
    status: str
    capabilities: list[str]
    organization_id: uuid.UUID | None = None
    center_id: uuid.UUID | None = None
    display_name: str | None = None


class Me(BaseModel):
    subject: str
    memberships: list[MembershipView]


class Network(BaseModel):
    id: uuid.UUID
    name: str
    country: str


class Registered(BaseModel):
    membership_id: uuid.UUID
    tenant_id: uuid.UUID
    status: Literal["pending"]


class PendingRegistration(BaseModel):
    membership_id: uuid.UUID
    tenant_id: uuid.UUID
    type: Literal["ngo", "donor", "member"]
    organization_name: str  # for a member: the name they chose
    role: str | None = None
    display_name: str | None = None
    country: str | None = None
    donor_type: str | None = None
    created_at: datetime


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    center_id: uuid.UUID | None = None  # required to approve centre staff


class DecisionResult(BaseModel):
    membership_id: uuid.UUID
    status: Literal["active", "rejected"]


@router.get("/me", response_model=Me)
def get_me(identity: Identity = Depends(current_identity)) -> Me:
    """Works without a membership: the web app uses it to decide which screens to show."""
    names = {n["id"]: n["name"] for n in network_directory()}
    return Me(
        subject=identity.sub,
        memberships=[
            MembershipView(
                membership_id=m.id,
                tenant_id=m.tenant_id,
                network_name=names.get(m.tenant_id),
                role=m.role,
                status=m.status,
                capabilities=list(CAPABILITIES[m.role]) if m.status == "active" else [],
                organization_id=m.organization_id,
                center_id=m.center_id,
                display_name=m.display_name,
            )
            for m in memberships(identity.sub)
        ],
    )


@router.get("/networks", response_model=list[Network])
def get_networks(identity: Identity = Depends(current_identity)) -> list[dict]:
    """Active NGO networks a donor can join (public columns only)."""
    return network_directory()


@router.post("/registrations", response_model=Registered, status_code=201)
def post_registration(body: Registration, identity: Identity = Depends(current_identity)) -> dict:
    return register(identity, body, current_correlation_id())


@router.get("/admin/registrations", response_model=list[PendingRegistration])
def get_pending(claims: Claims = Depends(require_roles("org_admin", "platform_admin"))) -> list[dict]:
    return pending(claims)


@router.post("/admin/registrations/{membership_id}/decision", response_model=DecisionResult)
def post_decision(
    membership_id: uuid.UUID,
    body: Decision,
    claims: Claims = Depends(require_roles("org_admin", "platform_admin")),
) -> DecisionResult:
    status = decide(claims, membership_id, body.approve, current_correlation_id(), center_id=body.center_id)
    return DecisionResult(membership_id=membership_id, status=status)
