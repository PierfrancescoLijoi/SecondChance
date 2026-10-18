import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.principal import Claims


def list_offers(session: Session, donor_id: uuid.UUID | None = None) -> list[dict]:
    """No tenant filter on purpose: RLS scopes the rows (ADR-003). A donor sees only its own."""
    rows = session.execute(
        text(
            "SELECT id, tenant_id, category, quantity, unit, date_kind, expires_on,"
            " storage, status, version FROM donation_offer"
            " WHERE CAST(:donor AS uuid) IS NULL OR donor_id = CAST(:donor AS uuid)"
            " ORDER BY created_at, id"
        ),
        {"donor": donor_id},
    ).mappings()
    return [dict(row) for row in rows]


def create_offer(session: Session, donor: Claims, offer: dict, correlation_id: str) -> uuid.UUID:
    """FR-010: published directly as available; the donor organisation comes from the membership."""
    offer_id = session.execute(
        text(
            "INSERT INTO donation_offer (donor_id, category, quantity, unit, date_kind, expires_on,"
            " storage, pickup_from, pickup_until, status)"
            " VALUES (:donor, :category, :quantity, :unit, :date_kind, :expires_on,"
            " :storage, :pickup_from, :pickup_until, 'available') RETURNING id"
        ),
        offer | {"donor": donor.organization_id},
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO audit_event (actor, actor_role, action, object_type, object_id, outcome, correlation_id)"
            " VALUES (:actor, :role, 'offer.create', 'donation_offer', :id, 'success', :cid)"
        ),
        {"actor": donor.sub, "role": donor.role, "id": offer_id, "cid": correlation_id},
    )
    return offer_id


def reserve_offer(
    session: Session,
    offer_id: uuid.UUID,
    expected_version: int,
    actor: Claims,
    correlation_id: str,
) -> int | None:
    """Optimistic lock (FR-016): only the caller holding the current version wins.

    Returns the new version, or None if the offer changed, is not available or
    belongs to another tenant. The audit event shares the transaction (ADR-005).
    """
    new_version = session.execute(
        text(
            "UPDATE donation_offer"
            " SET status = 'reserved', version = version + 1, updated_at = now()"
            " WHERE id = :id AND status = 'available' AND version = :version"
            " RETURNING version"
        ),
        {"id": offer_id, "version": expected_version},
    ).scalar_one_or_none()
    if new_version is not None:
        session.execute(
            text(
                "INSERT INTO audit_event"
                " (actor, actor_role, action, object_type, object_id, outcome, correlation_id)"
                " VALUES (:actor, :role, 'offer.reserve', 'donation_offer', :id, 'success', :cid)"
            ),
            {"actor": actor.sub, "role": actor.role, "id": offer_id, "cid": correlation_id},
        )
    return new_version
