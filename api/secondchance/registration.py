"""Self-registration as NGO or donor, and its approval (ADR-017).

Everything a registration creates starts pending; database guards (migration 0003)
refuse anything else from the API role, whatever this code does.
"""

import uuid
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.admission import LIMITS, reject
from secondchance.auth import Identity
from secondchance.db import subject_transaction, tenant_transaction
from secondchance.identity import Claims, memberships

REGISTRANT = "registrant"  # app.role during registration: not an admin, so guards apply


class NgoRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ngo"]
    organization_name: str = Field(min_length=2, max_length=120)
    country: str = Field(pattern=r"^[A-Z]{2}$")


class DonorRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["donor"]
    network_id: uuid.UUID
    organization_name: str = Field(min_length=2, max_length=120)
    donor_type: Literal["supermarket", "restaurant", "canteen", "producer", "wholesaler", "other"]


class MemberRegistration(BaseModel):
    """Volunteers, centre staff and coordinators join an existing network; its admin decides (ADR-017)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["member"]
    network_id: uuid.UUID
    role: Literal["volunteer", "center_staff", "coordinator"]
    display_name: str = Field(min_length=1, max_length=80, pattern=r"^[^<>@]+$")  # a name to be recognised by, no contacts


Registration = Annotated[NgoRegistration | DonorRegistration | MemberRegistration, Field(discriminator="type")]
MEMBER_ROLES = ("donor", "volunteer", "center_staff", "coordinator")  # what a network admin decides


def _audit(session: Session, actor: str, role: str, action: str, object_id: uuid.UUID, cid: str) -> None:
    session.execute(
        text(
            "INSERT INTO audit_event (actor, actor_role, action, object_type, object_id, outcome, correlation_id)"
            " VALUES (:actor, :role, :action, 'membership', :id, 'success', :cid)"
        ),
        {"actor": actor, "role": role, "action": action, "id": object_id, "cid": cid},
    )


def network_directory() -> list[dict]:
    with subject_transaction("") as session:
        return [dict(r) for r in session.execute(text("SELECT id, name, country FROM network_directory ORDER BY name")).mappings()]


def register(identity: Identity, body: NgoRegistration | DonorRegistration | MemberRegistration, correlation_id: str) -> dict:
    existing = memberships(identity.sub)
    if len(existing) >= LIMITS["registrations_per_subject"]:
        raise reject("quota", "too many registrations for this account", retry_after=86400)

    if body.type == "ngo":
        tenant_id = uuid.uuid4()
        with tenant_transaction(tenant_id, REGISTRANT, identity.sub) as session:
            session.execute(
                text("INSERT INTO tenant (id, name, country, status, kind) VALUES (:id, :name, :country, 'pending', 'network')"),
                {"id": tenant_id, "name": body.organization_name, "country": body.country},
            )
            membership_id = _create_member(session, identity.sub, body.organization_name, "ngo", None, "org_admin")
            _audit(session, identity.sub, REGISTRANT, "registration.ngo", membership_id, correlation_id)
        return {"membership_id": membership_id, "tenant_id": tenant_id, "status": "pending"}

    with subject_transaction(identity.sub) as session:
        listed = session.execute(
            text("SELECT 1 FROM network_directory WHERE id = :id"), {"id": body.network_id}
        ).scalar_one_or_none()
    if listed is None:
        raise HTTPException(404, "network not found")
    if any(m.tenant_id == body.network_id for m in existing):
        raise HTTPException(409, "already registered in this network")
    with tenant_transaction(body.network_id, REGISTRANT, identity.sub) as session:
        if body.type == "member":
            membership_id = session.execute(
                text("INSERT INTO membership (subject, role, status, display_name)"
                     " VALUES (:sub, :role, 'pending', :name) RETURNING id"),
                {"sub": identity.sub, "role": body.role, "name": body.display_name.strip()},
            ).scalar_one()
            _audit(session, identity.sub, REGISTRANT, f"registration.{body.role}", membership_id, correlation_id)
        else:
            membership_id = _create_member(session, identity.sub, body.organization_name, "donor", body.donor_type, "donor")
            _audit(session, identity.sub, REGISTRANT, "registration.donor", membership_id, correlation_id)
    return {"membership_id": membership_id, "tenant_id": body.network_id, "status": "pending"}


def _create_member(session: Session, subject: str, name: str, kind: str, donor_type: str | None, role: str) -> uuid.UUID:
    organization_id = session.execute(
        text("INSERT INTO organization (name, kind, donor_type, status) VALUES (:name, :kind, :donor_type, 'pending') RETURNING id"),
        {"name": name, "kind": kind, "donor_type": donor_type},
    ).scalar_one()
    return session.execute(
        text("INSERT INTO membership (subject, organization_id, role, status) VALUES (:sub, :org, :role, 'pending') RETURNING id"),
        {"sub": subject, "org": organization_id, "role": role},
    ).scalar_one()


def pending(claims: Claims) -> list[dict]:
    """What this admin may decide: donors of their network, or new networks for the platform."""
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        if claims.role == "platform_admin":
            rows = session.execute(
                text("SELECT membership_id, tenant_id, name AS organization_name, country, created_at, 'ngo' AS type"
                     " FROM network_registration_queue ORDER BY created_at")
            )
        else:
            rows = session.execute(
                text(
                    "SELECT m.id AS membership_id, m.tenant_id, coalesce(o.name, m.display_name) AS organization_name,"
                    " o.donor_type, m.role, m.display_name, m.created_at,"
                    " CASE WHEN m.role = 'donor' THEN 'donor' ELSE 'member' END AS type"
                    " FROM membership m LEFT JOIN organization o ON o.id = m.organization_id"
                    " WHERE m.status = 'pending' AND m.role = ANY(:roles) ORDER BY m.created_at"
                ),
                {"roles": list(MEMBER_ROLES)},
            )
        return [dict(r) for r in rows.mappings()]


def decide(claims: Claims, membership_id: uuid.UUID, approve: bool, correlation_id: str,
           center_id: uuid.UUID | None = None) -> str:
    outcome = "active" if approve else "rejected"
    if claims.role == "platform_admin":
        with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
            tenant_id = session.execute(
                text("SELECT tenant_id FROM network_registration_queue WHERE membership_id = :id"), {"id": membership_id}
            ).scalar_one_or_none()
        if tenant_id is None:
            raise HTTPException(404, "registration not found or already decided")
        if center_id is not None:
            raise HTTPException(422, "a centre is assigned only to centre staff")
        # Acts inside the new network's own tenant context: RLS still applies to every write.
        with tenant_transaction(tenant_id, "platform_admin", claims.sub) as session:
            session.execute(
                text("UPDATE tenant SET status = :status WHERE id = :id"),
                {"status": "active" if approve else "suspended", "id": tenant_id},
            )
            _decide_member(session, claims.sub, membership_id, outcome, correlation_id)
        return outcome

    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        role = session.execute(
            text("SELECT role FROM membership WHERE id = :id AND status = 'pending'"), {"id": membership_id}
        ).scalar_one_or_none()
        if role not in MEMBER_ROLES:
            raise HTTPException(404, "registration not found or already decided")
        if center_id is not None and role != "center_staff":
            raise HTTPException(422, "a centre is assigned only to centre staff")
        if role == "center_staff" and approve:
            if center_id is None:
                raise HTTPException(422, "approving centre staff needs the centre they work for")
            if session.execute(text("SELECT 1 FROM center WHERE id = :id"), {"id": center_id}).scalar_one_or_none() is None:
                raise HTTPException(422, "centre not found in this network")
            session.execute(text("UPDATE membership SET center_id = :center WHERE id = :id"),
                            {"center": center_id, "id": membership_id})
        _decide_member(session, claims.sub, membership_id, outcome, correlation_id)
    return outcome


def _decide_member(session: Session, actor: str, membership_id: uuid.UUID, outcome: str, cid: str) -> None:
    decided = session.execute(
        text(
            "UPDATE membership SET status = :status, decided_by = :actor, decided_at = now()"
            " WHERE id = :id AND status = 'pending' RETURNING organization_id"
        ),
        {"status": outcome, "actor": actor, "id": membership_id},
    ).one_or_none()
    if decided is None:
        raise HTTPException(404, "registration not found or already decided")
    organization_id = decided.organization_id  # NULL for volunteers, centre staff and coordinators
    if organization_id is not None:
        session.execute(
            text("UPDATE organization SET status = :status WHERE id = :id"),
            {"status": "active" if outcome == "active" else "suspended", "id": organization_id},
        )
    role = session.execute(text("SELECT current_setting('app.role')")).scalar_one()
    _audit(session, actor, role, f"registration.{outcome}", membership_id, cid)
