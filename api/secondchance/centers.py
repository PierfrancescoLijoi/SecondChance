"""Receiving centres: configuration, capacity and acceptance slots (FR-003, FR-014).

An org admin manages every centre of the network; centre staff manage only the centre an admin
assigned to them (membership.center_id). Changes are optimistic (version) and audited. Slot times
are local to the centre's IANA time zone; PostgreSQL converts them, so the application never
needs its own copy of the time zone database.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance import audit
from secondchance.principal import Claims

_CENTERS = (
    "SELECT c.id, c.name, c.status, c.address, ST_Y(c.location::geometry) AS latitude,"
    " ST_X(c.location::geometry) AS longitude, c.timezone, c.accepted_categories, c.storage_capabilities,"
    " c.daily_capacity_kg, c.version, c.updated_at,"
    " coalesce((SELECT sum(m.quantity * CASE m.unit WHEN 'pcs' THEN 0.5 ELSE 1 END) FROM mission m"
    "   WHERE m.center_id = c.id AND m.status IN ('assigned', 'accepted', 'picked_up', 'delivered')"
    "   AND (m.deliver_after AT TIME ZONE c.timezone)::date = (now() AT TIME ZONE c.timezone)::date), 0)"
    "   AS committed_today_kg"
    " FROM center c WHERE CAST(:only AS uuid) IS NULL OR c.id = CAST(:only AS uuid) ORDER BY c.name, c.id"
)


def may_manage(claims: Claims, center_id: uuid.UUID) -> bool:
    return claims.role == "org_admin" or (claims.role == "center_staff" and claims.center_id == center_id)


def list_centers(session: Session, only: uuid.UUID | None = None) -> list[dict]:
    centers = [dict(row) for row in session.execute(text(_CENTERS), {"only": only}).mappings()]
    slots: dict[uuid.UUID, list[dict]] = {}
    for row in session.execute(
        text(
            "SELECT center_id, weekday, opens, closes FROM center_slot"
            " WHERE CAST(:only AS uuid) IS NULL OR center_id = CAST(:only AS uuid) ORDER BY center_id, weekday, opens"
        ),
        {"only": only},
    ).mappings():
        slots.setdefault(row["center_id"], []).append({k: row[k] for k in ("weekday", "opens", "closes")})
    for center in centers:
        center["slots"] = slots.get(center["id"], [])
    return centers


def _check_timezone(session: Session, timezone: str) -> None:
    known = session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = :tz)"), {"tz": timezone}
    ).scalar_one()
    if not known:
        raise HTTPException(422, "unknown time zone")


def _point(data: dict) -> dict:
    return {"lat": data.get("latitude"), "lon": data.get("longitude")}


def create_center(session: Session, claims: Claims, data: dict, correlation_id: str) -> uuid.UUID:
    _check_timezone(session, data["timezone"])
    organization_id = claims.organization_id or session.execute(
        text("SELECT id FROM organization WHERE kind = 'ngo' ORDER BY created_at, id LIMIT 1")
    ).scalar_one_or_none()
    if organization_id is None:
        raise HTTPException(409, "the network has no NGO organisation to operate the centre")
    center_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO center (id, organization_id, name, status, address, location, timezone,"
            " accepted_categories, storage_capabilities, daily_capacity_kg)"
            " VALUES (:id, :org, :name, :status, :address,"
            " CASE WHEN CAST(:lat AS float8) IS NULL THEN NULL"
            " ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS float8), CAST(:lat AS float8)), 4326)::geography END,"
            " :timezone, :categories, :storage, :capacity)"
        ),
        {
            "id": center_id, "org": organization_id, "name": data["name"], "status": data["status"],
            "address": data.get("address"), "timezone": data["timezone"], "categories": data["accepted_categories"],
            "storage": data["storage_capabilities"], "capacity": data["daily_capacity_kg"], **_point(data),
        },
    )
    audit.record(session, claims.sub, claims.role, "center.create", "center", center_id, correlation_id)
    return center_id


def update_center(session: Session, claims: Claims, center_id: uuid.UUID, data: dict, correlation_id: str) -> int:
    _check_timezone(session, data["timezone"])
    version = session.execute(
        text(
            "UPDATE center SET name = :name, status = :status, address = :address,"
            " location = CASE WHEN CAST(:lat AS float8) IS NULL THEN NULL"
            " ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS float8), CAST(:lat AS float8)), 4326)::geography END,"
            " timezone = :timezone,"
            " accepted_categories = :categories, storage_capabilities = :storage, daily_capacity_kg = :capacity,"
            " version = version + 1, updated_at = now()"
            " WHERE id = :id AND version = :version RETURNING version"
        ),
        {
            "id": center_id, "version": data["version"], "name": data["name"], "status": data["status"],
            "address": data.get("address"), "timezone": data["timezone"], "categories": data["accepted_categories"],
            "storage": data["storage_capabilities"], "capacity": data["daily_capacity_kg"], **_point(data),
        },
    ).scalar_one_or_none()
    if version is None:
        _missing_or_conflict(session, center_id)
    audit.record(session, claims.sub, claims.role, "center.update", "center", center_id, correlation_id,
                 {"status": data["status"], "daily_capacity_kg": data["daily_capacity_kg"]})
    return version


def replace_slots(
    session: Session, claims: Claims, center_id: uuid.UUID, version: int, slots: list[dict], correlation_id: str
) -> int:
    """All slots at once, under the centre's version: two editors never interleave half a week each."""
    new_version = session.execute(
        text("UPDATE center SET version = version + 1, updated_at = now() WHERE id = :id AND version = :version"
             " RETURNING version"),
        {"id": center_id, "version": version},
    ).scalar_one_or_none()
    if new_version is None:
        _missing_or_conflict(session, center_id)
    session.execute(text("DELETE FROM center_slot WHERE center_id = :id"), {"id": center_id})
    for slot in slots:
        session.execute(
            text("INSERT INTO center_slot (center_id, weekday, opens, closes) VALUES (:center, :weekday, :opens, :closes)"),
            {"center": center_id, **slot},
        )
    audit.record(session, claims.sub, claims.role, "center.slots", "center", center_id, correlation_id,
                 {"slots": len(slots)})
    return new_version


def set_organization_location(
    session: Session, claims: Claims, organization_id: uuid.UUID, latitude: float, longitude: float, correlation_id: str
) -> None:
    """Pickup coordinates for distance estimates: a donor sets its own, an org admin any in the network."""
    if claims.role == "donor" and claims.organization_id != organization_id:
        raise HTTPException(403, "donors set only their own organisation's location")
    updated = session.execute(
        text(
            "UPDATE organization SET location ="
            " ST_SetSRID(ST_MakePoint(CAST(:lon AS float8), CAST(:lat AS float8)), 4326)::geography WHERE id = :id"
        ),
        {"id": organization_id, "lat": latitude, "lon": longitude},
    ).rowcount
    if updated == 0:
        raise HTTPException(404, "organisation not found")
    audit.record(session, claims.sub, claims.role, "organization.location", "organization", organization_id, correlation_id)


def _missing_or_conflict(session: Session, center_id: uuid.UUID):
    exists = session.execute(text("SELECT 1 FROM center WHERE id = :id"), {"id": center_id}).scalar_one_or_none()
    raise HTTPException(409 if exists else 404, "centre changed meanwhile: reload" if exists else "centre not found")
