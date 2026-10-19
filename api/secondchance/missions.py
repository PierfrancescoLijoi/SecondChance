"""Approved proposals become missions; missions move through an audited life cycle.

FR-022: a proposal is executed only by an authorised person who confirms its content hash. The
execution is deterministic application code in one transaction: it re-checks the centre, its
capacity and the volunteer, reserves the offer with the version the solver read (FR-016), creates
the mission, records the decision, notifies and audits. Agents and the solver never reach it.

FR-023/FR-025/FR-027: transitions are checked here and again by the database trigger
guard_mission (migration 0009); each one bumps the version once, writes a mission_event and is
idempotent under an Idempotency-Key. A failure is handled by reassigning the same mission, so an
offer never has two live missions (unique index mission_one_live_per_offer).
"""

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance import audit
from secondchance.logistics import load_kg
from secondchance.matching import row_sha256
from secondchance.notifications import network_language, notify
from secondchance.observability import meter
from secondchance.principal import Claims

FAILURE_REASONS = ("declined", "donor_absent", "vehicle_issue", "quality_rejected", "cold_chain_broken",
                   "center_closed", "safety", "other")
CANCEL_REASONS = ("no_longer_needed", "offer_withdrawn", "duplicate", "other")
EXCEPTION_REASONS = ("partial", "quality_rejected", "cold_chain_broken", "damaged", "wrong_items", "other")
REJECT_REASONS = ("wrong_centre", "timing", "capacity", "quality_concern", "other")

VOLUNTEER_MOVES = {"accepted": ("assigned",), "picked_up": ("accepted",), "delivered": ("picked_up",),
                   "failed": ("assigned", "accepted", "picked_up")}
MANAGER_MOVES = {"cancelled": ("assigned", "accepted", "failed", "picked_up"),
                 "failed": ("assigned", "accepted", "picked_up"), "delivered": ("picked_up",)}

decisions_counter = meter.create_counter("secondchance.proposals.decisions", description="Proposal decisions by outcome")
transitions_counter = meter.create_counter("secondchance.missions.transitions", description="Mission transitions by target")

_MISSION_COLUMNS = (
    "SELECT m.id, m.status, m.version, m.offer_id, m.center_id, m.volunteer_subject, m.reassignments, m.failure_reason,"
    " m.quantity, m.unit, m.deliver_after, m.deliver_before, m.receipt, m.receipt_reason, m.received_quantity,"
    " m.created_by, m.created_at, m.updated_at, m.accepted_at, m.picked_up_at, m.delivered_at, m.received_at,"
    " o.category, o.storage, o.date_kind, o.expires_on, o.pickup_from, o.pickup_until,"
    " d.name AS donor_name, ST_Y(d.location::geometry) AS donor_latitude, ST_X(d.location::geometry) AS donor_longitude,"
    " c.name AS center_name, c.address AS center_address,"
    " (SELECT v.display_name FROM membership v WHERE v.subject = m.volunteer_subject AND v.role = 'volunteer'"
    "   ORDER BY v.created_at LIMIT 1) AS volunteer_name"
    " FROM mission m JOIN donation_offer o ON o.id = m.offer_id JOIN organization d ON d.id = o.donor_id"
    " JOIN center c ON c.id = m.center_id"
)


def _active_volunteer(session: Session, membership_id: uuid.UUID) -> str:
    subject = session.execute(
        text("SELECT subject FROM membership WHERE id = :id AND role = 'volunteer' AND status = 'active'"),
        {"id": membership_id},
    ).scalar_one_or_none()
    if subject is None:
        raise HTTPException(422, "volunteer is not an active member of this network")
    return subject


def _event(session: Session, mission_id: uuid.UUID, from_status: str | None, to_status: str, claims: Claims,
           reason: str | None, idempotency_key: str | None) -> None:
    session.execute(
        text(
            "INSERT INTO mission_event (mission_id, from_status, to_status, actor, actor_role, reason, idempotency_key)"
            " VALUES (:mission, :from_status, :to_status, :actor, :role, :reason, :key)"
        ),
        {"mission": mission_id, "from_status": from_status, "to_status": to_status, "actor": claims.sub,
         "role": claims.role, "reason": reason, "key": idempotency_key},
    )


def _center_staff(session: Session, center_id: uuid.UUID) -> list[str]:
    return list(session.execute(
        text("SELECT subject FROM membership WHERE center_id = :center AND role = 'center_staff' AND status = 'active'"),
        {"center": center_id},
    ).scalars())


def _bump_offer(session: Session, offer_id: uuid.UUID, from_status: str, to_status: str) -> None:
    session.execute(
        text("UPDATE donation_offer SET status = :to, version = version + 1, updated_at = now()"
             " WHERE id = :id AND status = :from_status"),
        {"id": offer_id, "to": to_status, "from_status": from_status},
    )


# --- proposals ---

def list_proposals(session: Session, status: str = "proposed", limit: int = 100) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT p.id, p.run_id, p.offer_id, p.offer_version, p.center_id, c.name AS center_name, p.quantity, p.unit,"
            " p.load_kg, p.score, p.distance_km, p.deliver_after, p.deliver_before, p.explanation, p.alternatives,"
            " p.content_sha256, p.status, p.decided_at, p.decision_reason, p.created_at,"
            " o.category, o.storage, o.date_kind, o.expires_on, o.pickup_from, o.pickup_until, d.name AS donor_name"
            " FROM allocation_proposal p JOIN center c ON c.id = p.center_id"
            " JOIN donation_offer o ON o.id = p.offer_id JOIN organization d ON d.id = o.donor_id"
            " WHERE p.status = :status ORDER BY p.deliver_after, p.id LIMIT :limit"
        ),
        {"status": status, "limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


def decide_proposal(session: Session, claims: Claims, proposal_id: uuid.UUID, decision: dict,
                    correlation_id: str) -> tuple[dict, list[dict | None]]:
    """Approve (execute) or reject one proposal. Returns the outcome and the emails to send after commit."""
    proposal = session.execute(
        text("SELECT p.*, o.category, o.storage FROM allocation_proposal p JOIN donation_offer o ON o.id = p.offer_id"
             " WHERE p.id = :id FOR UPDATE OF p"),
        {"id": proposal_id},
    ).mappings().one_or_none()
    if proposal is None:
        raise HTTPException(404, "proposal not found")
    if proposal["status"] != "proposed":
        decisions_counter.add(1, {"outcome": "already_decided"})
        raise HTTPException(409, f"proposal is {proposal['status']}: reload the proposals")
    # The approver confirms exactly what they saw; the stored content must still hash to the same value.
    if decision["content_sha256"] != proposal["content_sha256"] or row_sha256(proposal) != proposal["content_sha256"]:
        decisions_counter.add(1, {"outcome": "content_mismatch"})
        raise HTTPException(409, "proposal content does not match what was reviewed: reload")

    if not decision["approve"]:
        reason = decision.get("reason") or "other"
        session.execute(
            text("UPDATE allocation_proposal SET status = 'rejected', decided_by = :actor, decided_at = now(),"
                 " decision_reason = :reason WHERE id = :id"),
            {"actor": claims.sub, "reason": reason, "id": proposal_id},
        )
        audit.record(session, claims.sub, claims.role, "proposal.reject", "allocation_proposal", proposal_id,
                     correlation_id, {"reason": reason})
        decisions_counter.add(1, {"outcome": "rejected"})
        return {"proposal_id": proposal_id, "status": "rejected", "mission_id": None}, []

    center_id, deliver_after, deliver_before = proposal["center_id"], proposal["deliver_after"], proposal["deliver_before"]
    chosen = decision.get("center_id")
    if chosen is not None and chosen != center_id:
        alternative = next((a for a in proposal["alternatives"] if a["center_id"] == str(chosen)), None)
        if alternative is None:
            raise HTTPException(422, "the chosen centre is not one of the proposal's alternatives")
        center_id = chosen
        deliver_after = datetime.fromisoformat(alternative["deliver_after"])
        deliver_before = datetime.fromisoformat(alternative["deliver_before"])
    volunteer = _active_volunteer(session, decision["volunteer_membership_id"])

    # Deterministic re-check against the current state: the world may have moved since the solver ran.
    center = session.execute(
        text(
            "SELECT c.daily_capacity_kg, coalesce((SELECT sum(m.quantity * CASE m.unit WHEN 'pcs' THEN 0.5 ELSE 1 END)"
            "   FROM mission m WHERE m.center_id = c.id AND m.status IN ('assigned', 'accepted', 'picked_up', 'delivered')"
            "   AND (m.deliver_after AT TIME ZONE c.timezone)::date = (CAST(:after AS timestamptz) AT TIME ZONE c.timezone)::date),"
            "   0) AS committed"
            " FROM center c WHERE c.id = :id AND c.status = 'active'"
            " AND :category = ANY(c.accepted_categories) AND :storage = ANY(c.storage_capabilities) FOR UPDATE OF c"
        ),
        {"id": center_id, "after": deliver_after, "category": proposal["category"], "storage": proposal["storage"]},
    ).mappings().one_or_none()
    if center is None:
        raise HTTPException(409, "the centre no longer accepts this offer: run matching again")
    if float(center["committed"]) + load_kg(proposal["quantity"], proposal["unit"]) > float(center["daily_capacity_kg"]):
        raise HTTPException(409, "the centre has no capacity left that day: run matching again")
    reserved = session.execute(
        text("UPDATE donation_offer SET status = 'reserved', version = version + 1, updated_at = now()"
             " WHERE id = :id AND status = 'available' AND version = :version RETURNING version"),
        {"id": proposal["offer_id"], "version": proposal["offer_version"]},
    ).scalar_one_or_none()
    if reserved is None:
        decisions_counter.add(1, {"outcome": "offer_conflict"})
        raise HTTPException(409, "the offer changed or was reserved meanwhile: run matching again")

    mission_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO mission (id, proposal_id, offer_id, center_id, volunteer_subject, quantity, unit,"
            " deliver_after, deliver_before, created_by)"
            " VALUES (:id, :proposal, :offer, :center, :volunteer, :quantity, :unit, :after, :before, :actor)"
        ),
        {"id": mission_id, "proposal": proposal_id, "offer": proposal["offer_id"], "center": center_id,
         "volunteer": volunteer, "quantity": proposal["quantity"], "unit": proposal["unit"], "after": deliver_after,
         "before": deliver_before, "actor": claims.sub},
    )
    session.execute(
        text("UPDATE allocation_proposal SET status = 'approved', decided_by = :actor, decided_at = now(),"
             " approved_center_id = :center WHERE id = :id"),
        {"actor": claims.sub, "center": center_id, "id": proposal_id},
    )
    _event(session, mission_id, None, "assigned", claims, "approved", None)
    language = network_language(session)
    emails = [notify(session, recipient=volunteer, kind="mission_assigned", object_type="mission",
                     object_id=mission_id, language=language)]
    for staff in _center_staff(session, center_id):
        notify(session, recipient=staff, kind="delivery_incoming", object_type="mission", object_id=mission_id)
    audit.record(session, claims.sub, claims.role, "proposal.approve", "allocation_proposal", proposal_id, correlation_id,
                 {"mission_id": mission_id, "center_id": center_id, "changed_centre": center_id != proposal["center_id"]})
    decisions_counter.add(1, {"outcome": "approved"})
    return {"proposal_id": proposal_id, "status": "approved", "mission_id": mission_id}, emails


def list_volunteers(session: Session) -> list[dict]:
    """Active volunteers and their open workload; the subject (an identity-provider id) is never exposed."""
    rows = session.execute(
        text(
            "SELECT v.id AS membership_id, coalesce(v.display_name, 'Volunteer ' || left(v.id::text, 6)) AS display_name,"
            " count(m.id) FILTER (WHERE m.status IN ('assigned', 'accepted', 'picked_up')) AS open_missions"
            " FROM membership v LEFT JOIN mission m ON m.volunteer_subject = v.subject AND m.tenant_id = v.tenant_id"
            " WHERE v.role = 'volunteer' AND v.status = 'active'"
            " GROUP BY v.id, v.display_name ORDER BY open_missions, display_name, v.id"
        )
    ).mappings()
    return [dict(r) for r in rows]


# --- missions ---

def list_missions(session: Session, claims: Claims, status: str | None = None, center_id: uuid.UUID | None = None,
                  limit: int = 200) -> list[dict]:
    """RLS decides the rows: operators see the network, volunteers their own, centre staff their centre."""
    rows = session.execute(
        text(
            _MISSION_COLUMNS
            + " WHERE (CAST(:status AS text) IS NULL OR m.status = CAST(:status AS text))"
            " AND (CAST(:center AS uuid) IS NULL OR m.center_id = CAST(:center AS uuid))"
            " ORDER BY m.deliver_after, m.id LIMIT :limit"
        ),
        {"status": status, "center": center_id, "limit": limit},
    ).mappings()
    return [_view(dict(r), claims) for r in rows]


def get_mission(session: Session, claims: Claims, mission_id: uuid.UUID) -> dict:
    row = session.execute(text(_MISSION_COLUMNS + " WHERE m.id = :id"), {"id": mission_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "mission not found")
    events = session.execute(
        text("SELECT from_status, to_status, actor_role, reason, occurred_at FROM mission_event"
             " WHERE mission_id = :id ORDER BY occurred_at, id"),
        {"id": mission_id},
    ).mappings()
    return _view(dict(row), claims) | {"events": [dict(e) for e in events]}


def _view(row: dict, claims: Claims) -> dict:
    mine = row.pop("volunteer_subject") == claims.sub
    row.pop("created_by")
    return row | {"assigned_to_me": mine}


def _locked(session: Session, mission_id: uuid.UUID) -> dict:
    row = session.execute(
        text("SELECT id, status, version, offer_id, center_id, volunteer_subject, quantity, unit, picked_up_at, created_by,"
             " receipt FROM mission WHERE id = :id FOR UPDATE"),
        {"id": mission_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "mission not found")
    return dict(row)


def _replayed(session: Session, mission_id: uuid.UUID, idempotency_key: str | None, target: str) -> bool:
    if not idempotency_key:
        return False
    recorded = session.execute(
        text("SELECT to_status FROM mission_event WHERE mission_id = :id AND idempotency_key = :key"),
        {"id": mission_id, "key": idempotency_key},
    ).scalar_one_or_none()
    if recorded is None:
        return False
    if recorded != target:
        raise HTTPException(409, "idempotency key already used for another change")
    return True


def transition(session: Session, claims: Claims, mission_id: uuid.UUID, target: str, version: int, reason: str | None,
               idempotency_key: str | None, correlation_id: str) -> tuple[dict, list[dict | None]]:
    mission = _locked(session, mission_id)  # serialises retries, so the replay check below is exact
    if _replayed(session, mission_id, idempotency_key, target):
        return {"id": mission_id, "replayed": True}, []
    if claims.role == "volunteer":
        allowed = VOLUNTEER_MOVES.get(target, ())
    elif claims.role in ("coordinator", "org_admin"):
        allowed = MANAGER_MOVES.get(target, ())
    else:
        raise HTTPException(403, "role not allowed to move missions")
    if mission["status"] not in allowed:
        raise HTTPException(409, f"a {mission['status']} mission cannot become {target}")
    if mission["version"] != version:
        raise HTTPException(409, "mission changed meanwhile: reload")
    if target == "failed" and reason not in FAILURE_REASONS:
        raise HTTPException(422, "a failure needs a reason code")
    if target == "cancelled" and reason not in CANCEL_REASONS:
        raise HTTPException(422, "a cancellation needs a reason code")
    stamp = {"accepted": "accepted_at", "picked_up": "picked_up_at", "delivered": "delivered_at"}.get(target)
    session.execute(
        text(
            "UPDATE mission SET status = :target, version = version + 1, updated_at = now(),"
            " failure_reason = CASE WHEN :target = 'failed' THEN :reason ELSE failure_reason END,"
            " accepted_at = CASE WHEN :stamp = 'accepted_at' THEN now() ELSE accepted_at END,"
            " picked_up_at = CASE WHEN :stamp = 'picked_up_at' THEN now() ELSE picked_up_at END,"
            " delivered_at = CASE WHEN :stamp = 'delivered_at' THEN now() ELSE delivered_at END"
            " WHERE id = :id"
        ),
        {"target": target, "reason": reason, "stamp": stamp, "id": mission_id},
    )
    if target == "picked_up":
        _bump_offer(session, mission["offer_id"], "reserved", "collected")
    elif target == "cancelled":
        # Before pickup the food is still at the donor: it goes back to the pool to be matched again.
        if mission["picked_up_at"] is None:
            _bump_offer(session, mission["offer_id"], "reserved", "available")
        else:
            _bump_offer(session, mission["offer_id"], "collected", "cancelled")
    _event(session, mission_id, mission["status"], target, claims, reason, idempotency_key)
    emails: list[dict | None] = []
    if target == "failed" and mission["created_by"] != claims.sub:
        notify(session, recipient=mission["created_by"], kind="mission_failed", object_type="mission", object_id=mission_id)
    if target == "cancelled" and mission["volunteer_subject"] != claims.sub:
        emails.append(notify(session, recipient=mission["volunteer_subject"], kind="mission_cancelled",
                             object_type="mission", object_id=mission_id, language=network_language(session)))
    audit.record(session, claims.sub, claims.role, f"mission.{target}", "mission", mission_id, correlation_id,
                 {"from": mission["status"], "reason": reason})
    transitions_counter.add(1, {"to": target})
    return {"id": mission_id, "replayed": False}, emails


def reassign(session: Session, claims: Claims, mission_id: uuid.UUID, volunteer_membership_id: uuid.UUID, version: int,
             correlation_id: str) -> tuple[dict, list[dict | None]]:
    """FR-025: the same mission gets a new volunteer; no duplicate is ever created."""
    mission = _locked(session, mission_id)
    if mission["status"] not in ("assigned", "accepted", "failed") or mission["picked_up_at"] is not None:
        raise HTTPException(409, "only a mission not yet picked up can be reassigned")
    if mission["version"] != version:
        raise HTTPException(409, "mission changed meanwhile: reload")
    volunteer = _active_volunteer(session, volunteer_membership_id)
    if volunteer == mission["volunteer_subject"] and mission["status"] != "failed":
        raise HTTPException(409, "the mission is already assigned to this volunteer")
    session.execute(
        text(
            "UPDATE mission SET volunteer_subject = :volunteer, status = 'assigned', version = version + 1,"
            " reassignments = reassignments + 1, failure_reason = NULL, accepted_at = NULL, updated_at = now()"
            " WHERE id = :id"
        ),
        {"volunteer": volunteer, "id": mission_id},
    )
    _event(session, mission_id, mission["status"], "assigned", claims, "reassigned", None)
    language = network_language(session)
    if mission["volunteer_subject"] != volunteer:
        notify(session, recipient=mission["volunteer_subject"], kind="mission_withdrawn", object_type="mission",
               object_id=mission_id)
    emails = [notify(session, recipient=volunteer, kind="mission_assigned", object_type="mission", object_id=mission_id,
                     language=language)]
    audit.record(session, claims.sub, claims.role, "mission.reassign", "mission", mission_id, correlation_id,
                 {"from": mission["status"]})
    transitions_counter.add(1, {"to": "reassigned"})
    return {"id": mission_id, "replayed": False}, emails


def record_receipt(session: Session, claims: Claims, mission_id: uuid.UUID, body: dict, correlation_id: str) -> dict:
    """The centre confirms receipt or records an exception (FL-01 step 7)."""
    mission = _locked(session, mission_id)
    if claims.role == "center_staff" and claims.center_id != mission["center_id"]:
        raise HTTPException(403, "this mission is for another centre")
    if claims.role not in ("center_staff", "coordinator", "org_admin"):
        raise HTTPException(403, "role not allowed to confirm receipts")
    if mission["status"] not in ("picked_up", "delivered") or mission["receipt"] is not None:
        raise HTTPException(409, "receipt can be recorded once, after pickup")
    if mission["version"] != body["version"]:
        raise HTTPException(409, "mission changed meanwhile: reload")
    quantity = float(mission["quantity"])
    received = quantity if body.get("received_quantity") is None else float(body["received_quantity"])
    if not 0 <= received <= quantity:
        raise HTTPException(422, "received quantity must be between 0 and the mission quantity")
    outcome, reason = body["outcome"], body.get("reason")
    if outcome == "confirmed" and received <= 0:
        raise HTTPException(422, "a confirmed receipt needs a received quantity")
    if outcome == "exception" and reason not in EXCEPTION_REASONS:
        raise HTTPException(422, "an exception needs a reason code")
    status = "delivered" if received > 0 else "failed"
    session.execute(
        text(
            "UPDATE mission SET receipt = :outcome, receipt_reason = :reason, received_quantity = :received,"
            " received_at = now(), delivered_at = coalesce(delivered_at, now()), status = :status,"
            " failure_reason = CASE WHEN :status = 'failed' THEN 'rejected_at_centre' ELSE failure_reason END,"
            " version = version + 1, updated_at = now() WHERE id = :id"
        ),
        {"outcome": outcome, "reason": reason, "received": received, "status": status, "id": mission_id},
    )
    _bump_offer(session, mission["offer_id"], "collected", "delivered" if received > 0 else "cancelled")
    _event(session, mission_id, mission["status"], status, claims, reason or "receipt_confirmed", None)
    if outcome == "exception" and mission["created_by"] != claims.sub:
        notify(session, recipient=mission["created_by"], kind="receipt_exception", object_type="mission", object_id=mission_id)
    audit.record(session, claims.sub, claims.role, f"mission.receipt_{outcome}", "mission", mission_id, correlation_id,
                 {"received_quantity": received, "reason": reason})
    transitions_counter.add(1, {"to": f"receipt_{outcome}"})
    return {"id": mission_id, "status": status}
