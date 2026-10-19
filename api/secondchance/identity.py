"""Authorization (ADR-017): memberships in the database decide tenant and role.

Every request resolves the subject's active membership, then opens a tenant transaction
with app.tenant_id, app.role and app.subject. Suspending a membership takes effect on
the next request, without waiting for the token to expire.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.auth import Identity, current_identity
from secondchance.db import subject_transaction, tenant_transaction
from secondchance.principal import Claims

ROLES = ("donor", "coordinator", "volunteer", "center_staff", "org_admin", "platform_admin")

# What each role's screens may offer. The backend enforces roles on every endpoint anyway.
CAPABILITIES: dict[str, tuple[str, ...]] = {
    "donor": ("offers.own", "offers.create", "knowledge.search", "assistant", "notifications"),
    "coordinator": (
        "offers.view", "offers.reserve", "assistant", "agents.run", "knowledge.search",
        "dashboard.view", "matching.run", "missions.manage", "centers.view", "notifications",
    ),
    "org_admin": (
        "offers.view", "registrations.review", "members.view", "documents.manage",
        "knowledge.search", "assistant", "agents.run", "settings",
        "dashboard.view", "matching.run", "missions.manage", "centers.manage", "notifications",
    ),
    "volunteer": ("missions.own", "knowledge.search", "notifications"),
    "center_staff": ("center.manage", "knowledge.search", "notifications"),
    "platform_admin": ("networks.review", "documents.manage", "knowledge.search"),
}
MANAGERS = ("coordinator", "org_admin")  # operators who approve allocations and steer missions


@dataclass(frozen=True)
class Membership:
    id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    status: str
    organization_id: uuid.UUID | None
    center_id: uuid.UUID | None = None
    display_name: str | None = None


def memberships(subject: str) -> list[Membership]:
    with subject_transaction(subject) as session:
        rows = session.execute(
            text(
                "SELECT id, tenant_id, role, status, organization_id, center_id, display_name FROM membership"
                " WHERE subject = :subject ORDER BY created_at"
            ),
            {"subject": subject},
        ).mappings()
        return [Membership(**row) for row in rows]


def current_claims(
    identity: Identity = Depends(current_identity),
    x_tenant_id: uuid.UUID | None = Header(default=None),
) -> Claims:
    active = [m for m in memberships(identity.sub) if m.status == "active"]
    if x_tenant_id is not None:
        active = [m for m in active if m.tenant_id == x_tenant_id]
    if not active:
        raise HTTPException(403, "no active membership: complete or await registration")
    if len(active) > 1:
        raise HTTPException(400, "member of several networks: send X-Tenant-ID")
    m = active[0]
    return Claims(
        sub=identity.sub, tenant_id=m.tenant_id, role=m.role, organization_id=m.organization_id, center_id=m.center_id
    )


def require_roles(*roles: str):
    """Dependency factory: 403 unless the caller's active role is one of `roles` (FR-002)."""

    def check(claims: Claims = Depends(current_claims)) -> Claims:
        if claims.role not in roles:
            raise HTTPException(403, "role not allowed for this operation")
        return claims

    return check


def tenant_session(claims: Claims = Depends(current_claims)) -> Iterator[Session]:
    """FastAPI dependency: commits on success, rolls back on any exception."""
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        yield session
