"""FL-01 end to end on a dedicated network: centres -> offers -> OR-Tools proposals -> human approval
bound to a content hash -> mission life cycle -> centre receipt -> notifications -> dashboard.

FR-003, FR-014, FR-016, FR-020..FR-023, FR-025..FR-027, FR-052, FR-053, plus the database guards and RLS
that hold whatever the application code does.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from secondchance import jobs, notifications
from secondchance.auth import mint_token
from secondchance.db import tenant_transaction
from secondchance.main import app
from secondchance.notifications import notify_queue
from secondchance.offers import expire_stale
from secondchance.queues import MemoryQueue
from secondchance.routes.knowledge import jobs_queue

client = TestClient(app)
SUFFIX = uuid.uuid4().hex[:8]
TENANT = uuid.uuid4()
NGO, DONOR = uuid.uuid4(), uuid.uuid4()
USERS = {role: f"ops-{role}-{SUFFIX}" for role in ("admin", "coordinator", "donor", "volunteer", "volunteer2", "staff",
                                                     "staff2")}
ALL_DAY = [{"weekday": d, "opens": "00:00", "closes": "23:59"} for d in range(1, 8)]
CATEGORIES = ["dairy", "dry_goods", "bakery", "fruit_vegetables", "ready_meals"]


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(USERS[key])}"}


@pytest.fixture(scope="module")
def network(migrator_engine) -> dict:
    """A fresh network arranged by the owner: the API cannot create active networks, by design (ADR-017)."""
    with migrator_engine.begin() as owner:
        owner.execute(text("INSERT INTO tenant (id, name, country, kind, status) VALUES (:id, 'Ops test network', 'IT',"
                           " 'network', 'active')"), {"id": TENANT})
        owner.execute(
            text("INSERT INTO organization (id, tenant_id, name, kind, donor_type, location) VALUES"
                 " (:ngo, :t, 'Ops NGO', 'ngo', NULL, NULL),"
                 " (:donor, :t, 'Ops Donor', 'donor', 'supermarket', ST_SetSRID(ST_MakePoint(7.68, 45.07), 4326)::geography)"),
            {"ngo": NGO, "donor": DONOR, "t": TENANT},
        )
        members = [("admin", "org_admin", NGO), ("coordinator", "coordinator", NGO), ("donor", "donor", DONOR),
                   ("volunteer", "volunteer", NGO), ("volunteer2", "volunteer", NGO)]
        for key, role, org in members:
            owner.execute(
                text("INSERT INTO membership (subject, tenant_id, organization_id, role, status, display_name)"
                     " VALUES (:sub, :t, :org, :role, 'active', :name)"),
                {"sub": USERS[key], "t": TENANT, "org": org, "role": role, "name": f"Ops {key}"},
            )
    centres = {}
    for key, body in {
        "a": {"name": "Ops Centre A", "address": "Via Test 1", "latitude": 45.08, "longitude": 7.69, "timezone": "Europe/Rome",
              "accepted_categories": CATEGORIES, "storage_capabilities": ["ambient", "chilled"], "daily_capacity_kg": 100},
        "b": {"name": "Ops Centre B", "address": "Via Test 2", "latitude": 45.20, "longitude": 7.80, "timezone": "Europe/Rome",
              "accepted_categories": CATEGORIES, "storage_capabilities": ["ambient"], "daily_capacity_kg": 60},
    }.items():
        created = client.post("/centers", json=body, headers=auth("admin"))
        assert created.status_code == 201, created.text
        centre = created.json()
        slots = client.post(f"/centers/{centre['id']}/slots", json={"version": centre["version"], "slots": ALL_DAY},
                            headers=auth("admin"))
        assert slots.status_code == 200, slots.text
        centres[key] = uuid.UUID(centre["id"])
    with migrator_engine.begin() as owner:  # centre staff exist only once their centre does
        for key, centre in (("staff", centres["a"]), ("staff2", centres["b"])):
            owner.execute(
                text("INSERT INTO membership (subject, tenant_id, organization_id, role, status, center_id)"
                     " VALUES (:sub, :t, :org, 'center_staff', 'active', :c)"),
                {"sub": USERS[key], "t": TENANT, "org": NGO, "c": centre},
            )
    return centres


@pytest.fixture
def queues():
    jobs_memory, notify_memory = MemoryQueue(), MemoryQueue()
    app.dependency_overrides[jobs_queue] = lambda: jobs_memory
    app.dependency_overrides[notify_queue] = lambda: notify_memory
    yield jobs_memory, notify_memory
    app.dependency_overrides.clear()


def publish(category: str, quantity: float, storage: str, date_kind: str = "use_by", expires_in: int = 2,
            unit: str = "kg") -> uuid.UUID:
    start = datetime.now(UTC) + timedelta(hours=1)
    response = client.post("/offers", headers=auth("donor"), json={
        "category": category, "quantity": quantity, "unit": unit, "date_kind": date_kind,
        "expires_on": (date.today() + timedelta(days=expires_in)).isoformat(), "storage": storage,
        "pickup_from": start.isoformat(), "pickup_until": (start + timedelta(hours=3)).isoformat(),
    })
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def run_matching(queues) -> dict:
    jobs_memory, _ = queues
    started = client.post("/matching-runs", json={"time_limit_seconds": 2}, headers=auth("coordinator"))
    assert started.status_code == 202, started.text
    message = jobs_memory.messages.popleft()
    assert message["type"] == "match" and set(message) == {"type", "tenant_id", "run_id", "correlation_id"}
    assert jobs.handle(message) in {"succeeded", "infeasible"}
    assert jobs.handle(message) == "not_claimable"  # SQS redelivery after completion is harmless
    run = client.get(f"/matching-runs/{started.json()['id']}", headers=auth("coordinator")).json()
    return run


def proposal_for(offer_id: uuid.UUID) -> dict:
    proposals = client.get("/proposals", headers=auth("coordinator")).json()
    return next(p for p in proposals if p["offer_id"] == str(offer_id))


def volunteer_membership(key: str) -> str:
    volunteers = client.get("/volunteers", headers=auth("coordinator")).json()
    return next(v["membership_id"] for v in volunteers if v["display_name"] == f"Ops {key}")


def approve(proposal: dict, volunteer: str = "volunteer", **extra):
    return client.post(f"/proposals/{proposal['id']}/decision", headers=auth("coordinator"), json={
        "approve": True, "content_sha256": proposal["content_sha256"],
        "volunteer_membership_id": volunteer_membership(volunteer), **extra,
    })


def mission(mission_id: str, key: str = "coordinator") -> dict:
    response = client.get(f"/missions/{mission_id}", headers=auth(key))
    assert response.status_code == 200, response.text
    return response.json()


def move(mission_id: str, key: str, to: str, reason: str | None = None, idempotency_key: str | None = None):
    current = mission(mission_id, key if key != "staff" else "coordinator")
    headers = auth(key) | ({"Idempotency-Key": idempotency_key} if idempotency_key else {})
    return client.post(f"/missions/{mission_id}/transition", headers=headers,
                       json={"to": to, "version": current["version"], **({"reason": reason} if reason else {})})


def offer_status(offer_id: uuid.UUID) -> str:
    with tenant_transaction(TENANT, "coordinator") as session:
        return session.execute(text("SELECT status FROM donation_offer WHERE id = :id"), {"id": offer_id}).scalar_one()


# --- centres ---

def test_centre_configuration_is_versioned_and_validated(network) -> None:
    centre = client.get(f"/centers/{network['a']}", headers=auth("admin")).json()
    assert centre["storage_capabilities"] == ["ambient", "chilled"] and len(centre["slots"]) == 7
    update = {k: centre[k] for k in ("name", "status", "address", "latitude", "longitude", "timezone",
                                      "accepted_categories", "storage_capabilities")}
    stale = client.post(f"/centers/{network['a']}", headers=auth("admin"),
                        json=update | {"daily_capacity_kg": 120, "version": centre["version"] - 1})
    assert stale.status_code == 409
    bad_zone = client.post(f"/centers/{network['a']}", headers=auth("admin"),
                           json=update | {"daily_capacity_kg": 100, "version": centre["version"], "timezone": "Mars/Base"})
    assert bad_zone.status_code == 422
    overlapping = client.post(f"/centers/{network['a']}/slots", headers=auth("admin"), json={
        "version": centre["version"], "slots": [{"weekday": 1, "opens": "08:00", "closes": "12:00"},
                                                 {"weekday": 1, "opens": "11:00", "closes": "13:00"}]})
    assert overlapping.status_code == 422


def test_centre_staff_manage_only_their_centre(network) -> None:
    assert [c["id"] for c in client.get("/centers", headers=auth("staff")).json()] == [str(network["a"])]
    assert client.get(f"/centers/{network['b']}", headers=auth("staff")).status_code == 403
    assert client.get("/centers", headers=auth("volunteer")).status_code == 403
    centre = client.get(f"/centers/{network['a']}", headers=auth("staff")).json()
    paused = {k: centre[k] for k in ("name", "address", "latitude", "longitude", "timezone", "accepted_categories",
                                     "storage_capabilities", "daily_capacity_kg")} | {"status": "active", "version": centre["version"]}
    assert client.post(f"/centers/{network['a']}", headers=auth("staff"), json=paused).status_code == 200
    assert client.post(f"/centers/{network['b']}", headers=auth("staff"), json=paused).status_code == 403
    assert client.post("/centers", headers=auth("staff"), json={k: v for k, v in paused.items() if k != "version"}).status_code == 403


def test_donor_sets_only_its_own_pickup_location(network) -> None:
    assert client.post(f"/organizations/{DONOR}/location", headers=auth("donor"),
                       json={"latitude": 45.07, "longitude": 7.68}).status_code == 204
    assert client.post(f"/organizations/{NGO}/location", headers=auth("donor"),
                       json={"latitude": 45.0, "longitude": 7.0}).status_code == 403


# --- FL-01: proposal -> approval -> mission -> receipt ---

def test_full_flow_from_offer_to_confirmed_receipt(network, queues) -> None:
    _, notify_memory = queues
    yogurt = publish("dairy", 20, "chilled")
    frozen = publish("ready_meals", 5, "frozen")  # no centre has frozen storage
    run = run_matching(queues)
    assert run["status"] == "succeeded" and run["solver_status"] == "OPTIMAL" and len(run["input_sha256"]) == 64
    unassigned = {u["offer_id"]: u["reasons"] for u in run["stats"]["unassigned"]}
    assert unassigned[str(frozen)] == ["storage_unavailable"]

    proposal = proposal_for(yogurt)
    assert proposal["center_id"] == str(network["a"])  # only centre A keeps chilled food
    assert proposal["generated_by"] == "secondchance-solver"
    assert offer_status(yogurt) == "available"  # a proposal reserves nothing (FR-022)

    tampered = approve(proposal | {"content_sha256": "0" * 64})
    assert tampered.status_code == 409
    approved = approve(proposal)
    assert approved.status_code == 200, approved.text
    mission_id = approved.json()["mission_id"]
    assert offer_status(yogurt) == "reserved"
    assert approve(proposal).status_code == 409  # one decision per proposal

    # The volunteer's email left after the commit, with identifiers only; the in-app row is theirs alone.
    [email] = list(notify_memory.messages)
    assert email["kind"] == "mission_assigned" and email["recipient"] == USERS["volunteer"] and email["language"] == "it"
    assert set(email) == {"type", "tenant_id", "delivery_id", "recipient", "kind", "language", "correlation_id"}
    inbox = client.get("/notifications?unread=true", headers=auth("volunteer")).json()
    assert inbox["unread"] >= 1 and inbox["items"][0]["object_id"] == mission_id
    assert all(item["object_id"] != mission_id for item in client.get("/notifications", headers=auth("coordinator")).json()["items"])
    staff_inbox = client.get("/notifications", headers=auth("staff")).json()["items"]
    assert any(item["kind"] == "delivery_incoming" and item["object_id"] == mission_id for item in staff_inbox)
    with tenant_transaction(TENANT, "coordinator") as session:
        assert session.execute(text("SELECT status FROM notification_delivery WHERE id = :id"),
                               {"id": email["delivery_id"]}).scalar_one() == "queued"

    # Volunteers see their own missions only; an idempotent retry changes nothing.
    assert [m["id"] for m in client.get("/missions", headers=auth("volunteer")).json()] == [mission_id]
    assert client.get("/missions", headers=auth("volunteer2")).json() == []
    assert client.get(f"/missions/{mission_id}", headers=auth("volunteer2")).status_code == 404
    first = move(mission_id, "volunteer", "accepted", idempotency_key="accept-" + mission_id)
    assert first.status_code == 200 and first.json()["status"] == "accepted"
    retry = client.post(f"/missions/{mission_id}/transition",
                        headers=auth("volunteer") | {"Idempotency-Key": "accept-" + mission_id},
                        json={"to": "accepted", "version": 1})
    assert retry.status_code == 200 and retry.json() == first.json() | {"replayed": True}
    assert move(mission_id, "volunteer", "delivered").status_code == 409  # pickup first
    assert move(mission_id, "volunteer", "picked_up").status_code == 200
    assert offer_status(yogurt) == "collected"
    assert move(mission_id, "volunteer", "delivered").status_code == 200

    # Centre B's staff cannot confirm a delivery to centre A; centre A's staff can, once.
    current = mission(mission_id)
    receipt = {"outcome": "confirmed", "received_quantity": 18, "version": current["version"]}
    assert client.post(f"/missions/{mission_id}/receipt", headers=auth("staff2"), json=receipt).status_code in (403, 404)
    confirmed = client.post(f"/missions/{mission_id}/receipt", headers=auth("staff"), json=receipt)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "delivered"
    assert client.post(f"/missions/{mission_id}/receipt", headers=auth("staff"),
                       json=receipt | {"version": confirmed.json()["version"]}).status_code == 409
    assert offer_status(yogurt) == "delivered"
    history = [(e["from_status"], e["to_status"]) for e in mission(mission_id)["events"]]
    assert history == [(None, "assigned"), ("assigned", "accepted"), ("accepted", "picked_up"),
                       ("picked_up", "delivered"), ("delivered", "delivered")]

    dashboard = client.get("/dashboard?days=7", headers=auth("coordinator")).json()
    assert dashboard["impact"]["kg_received"] >= 18 and dashboard["impact"]["receipts_confirmed"] >= 1
    assert dashboard["missions"]["by_status"]["delivered"] >= 1
    assert {c["name"] for c in dashboard["centres"]} == {"Ops Centre A", "Ops Centre B"}
    assert "volunteer" not in str(dashboard).lower()  # aggregates only (FR-053)
    assert client.get("/dashboard", headers=auth("volunteer")).status_code == 403


def test_operator_can_choose_an_alternative_centre(network, queues) -> None:
    pasta = publish("dry_goods", 10, "ambient", date_kind="best_before", expires_in=30)
    run_matching(queues)
    proposal = proposal_for(pasta)
    alternative = next(a for a in proposal["alternatives"] if a["center_id"] != proposal["center_id"])
    not_offered = approve(proposal, center_id=str(uuid.uuid4()))
    assert not_offered.status_code == 422
    approved = approve(proposal, center_id=alternative["center_id"])
    assert approved.status_code == 200, approved.text
    assert mission(approved.json()["mission_id"])["center_id"] == alternative["center_id"]


def test_a_new_run_supersedes_open_proposals_and_one_run_at_a_time(network, queues) -> None:
    bread = publish("bakery", 4, "ambient")
    run_matching(queues)
    old = proposal_for(bread)
    jobs_memory, _ = queues
    assert client.post("/matching-runs", json={}, headers=auth("coordinator")).status_code == 202
    assert client.post("/matching-runs", json={}, headers=auth("coordinator")).status_code == 429  # ADR-016
    assert jobs.handle(jobs_memory.messages.popleft()) == "succeeded"
    assert proposal_for(bread)["id"] != old["id"]
    assert approve(old).status_code == 409  # superseded


def test_concurrent_approvals_create_exactly_one_mission(network, queues) -> None:
    fruit = publish("fruit_vegetables", 6, "ambient")
    run_matching(queues)
    proposal = proposal_for(fruit)
    volunteer = volunteer_membership("volunteer")
    body = {"approve": True, "content_sha256": proposal["content_sha256"], "volunteer_membership_id": volunteer}
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(lambda _: client.post(f"/proposals/{proposal['id']}/decision", json=body,
                                                      headers=auth("coordinator")).status_code, range(2)))
    assert codes == [200, 409]
    with tenant_transaction(TENANT, "coordinator") as session:
        assert session.execute(text("SELECT count(*) FROM mission WHERE offer_id = :id"), {"id": fruit}).scalar_one() == 1


def test_failure_is_handled_by_reassignment_then_cancellation_frees_the_offer(network, queues) -> None:
    meal = publish("ready_meals", 3, "chilled")
    run_matching(queues)
    mission_id = approve(proposal_for(meal)).json()["mission_id"]
    assert move(mission_id, "volunteer", "failed").status_code == 422  # a failure needs a reason
    assert move(mission_id, "volunteer", "failed", reason="vehicle_issue").status_code == 200
    failed = mission(mission_id)
    assert failed["status"] == "failed" and offer_status(meal) == "reserved"
    reassigned = client.post(f"/missions/{mission_id}/reassign", headers=auth("coordinator"), json={
        "volunteer_membership_id": volunteer_membership("volunteer2"), "version": failed["version"]})
    assert reassigned.status_code == 200 and reassigned.json()["status"] == "assigned"
    assert mission(mission_id)["reassignments"] == 1
    assert [m["id"] for m in client.get("/missions", headers=auth("volunteer2")).json()] == [mission_id]
    assert all(m["id"] != mission_id for m in client.get("/missions", headers=auth("volunteer")).json())
    assert move(mission_id, "volunteer2", "cancelled", reason="other").status_code == 409  # volunteers do not cancel
    cancelled = move(mission_id, "coordinator", "cancelled", reason="no_longer_needed")
    assert cancelled.status_code == 200 and offer_status(meal) == "available"
    with tenant_transaction(TENANT, "coordinator") as session:
        missions = session.execute(text("SELECT count(*) FROM mission WHERE offer_id = :id"), {"id": meal}).scalar_one()
    assert missions == 1  # never a duplicate


def test_receipt_exception_with_nothing_received_fails_the_mission(network, queues) -> None:
    cheese = publish("dairy", 2, "chilled")
    run_matching(queues)
    mission_id = approve(proposal_for(cheese)).json()["mission_id"]
    for to in ("accepted", "picked_up"):
        assert move(mission_id, "volunteer", to).status_code == 200
    current = mission(mission_id)
    missing_reason = client.post(f"/missions/{mission_id}/receipt", headers=auth("staff"),
                                 json={"outcome": "exception", "received_quantity": 0, "version": current["version"]})
    assert missing_reason.status_code == 422
    exception = client.post(f"/missions/{mission_id}/receipt", headers=auth("staff"), json={
        "outcome": "exception", "received_quantity": 0, "reason": "cold_chain_broken", "version": current["version"]})
    assert exception.status_code == 200 and exception.json()["status"] == "failed"
    assert offer_status(cheese) == "cancelled"
    inbox = client.get("/notifications", headers=auth("coordinator")).json()["items"]
    assert any(n["kind"] == "receipt_exception" and n["object_id"] == mission_id for n in inbox)


def test_notifications_are_marked_read_by_their_recipient_only(network) -> None:
    items = client.get("/notifications?unread=true", headers=auth("volunteer")).json()["items"]
    assert items
    assert client.post(f"/notifications/{items[0]['id']}/read", headers=auth("coordinator")).status_code == 404
    assert client.post(f"/notifications/{items[0]['id']}/read", headers=auth("volunteer")).json() == {"marked": 1}
    client.post("/notifications/read-all", headers=auth("volunteer"))
    assert client.get("/notifications", headers=auth("volunteer")).json()["unread"] == 0


# --- the database refuses what the API role must never do ---

@pytest.mark.parametrize(
    ("role", "subject_key", "sql"),
    [
        ("coordinator", "coordinator",
         "INSERT INTO allocation_proposal (run_id, offer_id, offer_version, center_id, quantity, unit, load_kg, score,"
         " deliver_after, deliver_before, explanation, content_sha256) SELECT run_id, offer_id, offer_version, center_id,"
         " quantity, unit, load_kg, score, deliver_after, deliver_before, explanation, content_sha256"
         " FROM allocation_proposal LIMIT 1"),
        ("coordinator", "coordinator", "UPDATE allocation_proposal SET quantity = quantity + 1"),
        ("coordinator", "coordinator", "UPDATE allocation_proposal SET status = 'proposed' WHERE status <> 'proposed'"),
        ("volunteer2", "volunteer2", "UPDATE mission SET status = 'delivered', version = version + 1"),
        ("volunteer", "volunteer", "UPDATE mission SET volunteer_subject = 'someone-else', version = version + 1"),
        ("coordinator", "coordinator", "UPDATE mission SET status = 'delivered', version = version + 1 WHERE status = 'cancelled'"),
        ("coordinator", "coordinator", "UPDATE mission SET status = status, version = version WHERE true"),
        ("coordinator", "coordinator", "UPDATE donation_offer SET status = 'available', version = version + 1"
                                       " WHERE status = 'delivered'"),
    ],
    ids=["proposal-not-from-solver", "proposal-content", "proposal-reopen", "other-volunteer", "self-reassign",
         "revive-cancelled", "no-version-bump", "offer-backwards"],
)
def test_database_guards_hold_whatever_the_code_does(network, role: str, subject_key: str, sql: str) -> None:
    db_role = "volunteer" if role.startswith("volunteer") else role
    with pytest.raises(DBAPIError):
        with tenant_transaction(TENANT, db_role, USERS[subject_key]) as session:
            # Zero rows would prove nothing: fail loudly instead of passing without exercising the guard.
            assert session.execute(text(sql)).rowcount > 0, "nothing matched: the guard was not exercised"


def test_operations_tables_are_isolated_between_networks(network) -> None:
    from secondchance.seed import TENANT_DK

    with tenant_transaction(TENANT_DK, "coordinator") as session:
        for table in ("mission", "allocation_proposal", "matching_run", "center_slot", "notification_delivery"):
            ids = session.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": TENANT}).scalar_one()
            assert ids == 0, table


# --- recovery jobs (maintenance role) ---

def test_outbox_requeue_sends_pending_emails(network, maintenance_engine, owner) -> None:
    with tenant_transaction(TENANT, "coordinator", USERS["coordinator"]) as session:
        message = notifications.notify(session, recipient=USERS["volunteer"], kind="mission_cancelled",
                                       object_type="mission", object_id=uuid.uuid4(), language="it")
    owner.execute(text("UPDATE notification_delivery SET created_at = now() - interval '5 minutes' WHERE id = :id"),
                  {"id": message["delivery_id"]})
    queue = MemoryQueue()
    with maintenance_engine.begin() as connection:
        assert notifications.requeue_pending(connection, queue) >= 1
    sent = [m for m in queue.messages if m["delivery_id"] == message["delivery_id"]]
    assert len(sent) == 1 and sent[0]["recipient"] == USERS["volunteer"] and sent[0]["kind"] == "mission_cancelled"
    again = MemoryQueue()
    with maintenance_engine.begin() as connection:
        notifications.requeue_pending(connection, again)
    assert all(m["delivery_id"] != message["delivery_id"] for m in again.messages)  # queued once


def test_offers_past_their_window_expire_with_their_proposals(network, queues, maintenance_engine, owner) -> None:
    stale = publish("bakery", 1, "ambient")
    run_matching(queues)
    proposal = proposal_for(stale)
    owner.execute(text("UPDATE donation_offer SET pickup_from = now() - interval '3 hours',"
                       " pickup_until = now() - interval '1 hour' WHERE id = :id"), {"id": stale})
    with maintenance_engine.begin() as connection:
        assert expire_stale(connection) >= 1
    assert offer_status(stale) == "expired"
    with tenant_transaction(TENANT, "coordinator") as session:
        assert session.execute(text("SELECT status FROM allocation_proposal WHERE id = :id"),
                               {"id": proposal["id"]}).scalar_one() == "expired"


def test_lost_matching_messages_are_requeued(network, queues, maintenance_engine, owner) -> None:
    from secondchance.matching import requeue_stale

    jobs_memory, _ = queues
    started = client.post("/matching-runs", json={}, headers=auth("coordinator")).json()
    jobs_memory.messages.clear()  # the message is lost
    owner.execute(text("UPDATE matching_run SET created_at = now() - interval '5 minutes' WHERE id = :id"),
                  {"id": started["id"]})
    queue = MemoryQueue()
    with maintenance_engine.connect() as connection:
        assert requeue_stale(connection, queue) >= 1
    message = next(m for m in queue.messages if m["run_id"] == started["id"])
    assert jobs.handle(message) in {"succeeded", "infeasible"}


# --- membership for operations roles (ADR-017) ---

def test_volunteers_and_centre_staff_join_a_network_through_approval(network) -> None:
    from secondchance.seed import TENANT_IT, _id

    volunteer, staff = f"ops-new-vol-{SUFFIX}", f"ops-new-staff-{SUFFIX}"
    for subject, role in ((volunteer, "volunteer"), (staff, "center_staff")):
        created = client.post("/registrations", headers={"Authorization": f"Bearer {mint_token(subject)}"},
                              json={"type": "member", "network_id": str(TENANT_IT), "role": role, "display_name": f"New {role}"})
        assert created.status_code == 201, created.text
    admin = {"Authorization": f"Bearer {mint_token('demo-it-admin')}"}
    pending = {p["display_name"]: p for p in client.get("/admin/registrations", headers=admin).json()}
    assert pending["New volunteer"]["type"] == "member" and pending["New volunteer"]["role"] == "volunteer"
    staff_id = pending["New center_staff"]["membership_id"]
    assert client.post(f"/admin/registrations/{staff_id}/decision", headers=admin, json={"approve": True}).status_code == 422
    assert client.post(f"/admin/registrations/{pending['New volunteer']['membership_id']}/decision", headers=admin,
                       json={"approve": True, "center_id": str(_id("it/center/1"))}).status_code == 422
    assert client.post(f"/admin/registrations/{pending['New volunteer']['membership_id']}/decision", headers=admin,
                       json={"approve": True}).json()["status"] == "active"
    assert client.post(f"/admin/registrations/{staff_id}/decision", headers=admin,
                       json={"approve": True, "center_id": str(_id("it/center/1"))}).json()["status"] == "active"
    staff_auth = {"Authorization": f"Bearer {mint_token(staff)}"}
    [membership] = client.get("/me", headers=staff_auth).json()["memberships"]
    assert membership["center_id"] == str(_id("it/center/1")) and "center.manage" in membership["capabilities"]
    assert [c["id"] for c in client.get("/centers", headers=staff_auth).json()] == [str(_id("it/center/1"))]


def test_active_centre_staff_always_have_a_centre(network) -> None:
    from secondchance.seed import TENANT_IT

    with pytest.raises(DBAPIError, match="need a centre"):
        with tenant_transaction(TENANT_IT, "org_admin", "demo-it-admin") as session:
            membership = session.execute(
                text("INSERT INTO membership (subject, role, status) VALUES (:s, 'center_staff', 'pending') RETURNING id"),
                {"s": f"ops-orphan-{SUFFIX}"},
            ).scalar_one()
            session.execute(text("UPDATE membership SET status = 'active' WHERE id = :id"), {"id": membership})
