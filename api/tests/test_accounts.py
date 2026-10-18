"""ADR-017 registration and approval, ADR-016 early rejection, database guards on the API role."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from secondchance import admission
from secondchance.auth import mint_token
from secondchance.db import tenant_transaction
from secondchance.main import app
from secondchance.seed import TENANT_DK, TENANT_IT

client = TestClient(app)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(subject)}"}


def new_subject(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_me_without_membership_shows_nothing_to_do() -> None:
    me = client.get("/me", headers=auth(new_subject("fresh"))).json()
    assert me["memberships"] == []


def test_me_lists_capabilities_of_active_roles() -> None:
    [membership] = client.get("/me", headers=auth("demo-it-donor")).json()["memberships"]
    assert membership["role"] == "donor" and membership["status"] == "active"
    assert "offers.create" in membership["capabilities"] and "agents.run" not in membership["capabilities"]


def test_ngo_registration_waits_for_the_platform_admin() -> None:
    founder = new_subject("ngo")
    created = client.post(
        "/registrations", json={"type": "ngo", "organization_name": "Banco Test Milano", "country": "IT"}, headers=auth(founder)
    )
    assert created.status_code == 201
    registration = created.json()

    assert client.get("/offers", headers=auth(founder)).status_code == 403  # pending: no access yet
    [pending] = client.get("/me", headers=auth(founder)).json()["memberships"]
    assert (pending["status"], pending["capabilities"]) == ("pending", [])

    assert registration["membership_id"] not in {r["membership_id"] for r in client.get("/admin/registrations", headers=auth("demo-it-admin")).json()}
    queue = client.get("/admin/registrations", headers=auth("demo-platform-admin")).json()
    assert registration["membership_id"] in {r["membership_id"] for r in queue}

    decided = client.post(f"/admin/registrations/{registration['membership_id']}/decision", json={"approve": True},
                          headers=auth("demo-platform-admin"))
    assert decided.json()["status"] == "active"
    [active] = client.get("/me", headers=auth(founder)).json()["memberships"]
    assert (active["role"], active["status"]) == ("org_admin", "active")
    assert "registrations.review" in active["capabilities"]
    assert registration["tenant_id"] in {n["id"] for n in client.get("/networks", headers=auth(founder)).json()}


def test_donor_registration_is_approved_by_that_network_only() -> None:
    donor = new_subject("donor")
    created = client.post(
        "/registrations",
        json={"type": "donor", "network_id": str(TENANT_IT), "organization_name": "Forno Test", "donor_type": "producer"},
        headers=auth(donor),
    )
    assert created.status_code == 201
    membership_id = created.json()["membership_id"]

    other_network = client.post(f"/admin/registrations/{membership_id}/decision", json={"approve": True}, headers=auth("demo-dk-admin"))
    assert other_network.status_code == 404
    assert membership_id in {r["membership_id"] for r in client.get("/admin/registrations", headers=auth("demo-it-admin")).json()}

    approved = client.post(f"/admin/registrations/{membership_id}/decision", json={"approve": True}, headers=auth("demo-it-admin"))
    assert approved.json()["status"] == "active"
    assert client.get("/offers", headers=auth(donor)).status_code == 200


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"type": "ngo", "organization_name": "X Org", "country": "Italy"}, 422),
        ({"type": "ngo", "organization_name": "X Org", "country": "IT", "role": "platform_admin"}, 422),
        ({"type": "donor", "network_id": str(uuid.uuid4()), "organization_name": "X Org", "donor_type": "other"}, 404),
        ({"type": "admin", "organization_name": "X Org"}, 422),
    ],
    ids=["bad-country", "extra-field", "unknown-network", "unknown-type"],
)
def test_bad_registrations_are_rejected(body: dict, status: int) -> None:
    assert client.post("/registrations", json=body, headers=auth(new_subject("bad"))).status_code == status


def test_registering_twice_in_the_same_network_conflicts() -> None:
    donor = new_subject("twice")
    body = {"type": "donor", "network_id": str(TENANT_DK), "organization_name": "Bager Test", "donor_type": "producer"}
    assert client.post("/registrations", json=body, headers=auth(donor)).status_code == 201
    assert client.post("/registrations", json=body, headers=auth(donor)).status_code == 409


def test_registration_quota_per_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(admission.LIMITS, "registrations_per_subject", 0)
    body = {"type": "ngo", "organization_name": "Quota Org", "country": "DK"}
    response = client.post("/registrations", json=body, headers=auth(new_subject("quota")))
    assert response.status_code == 429 and "Retry-After" in response.headers


def test_agent_run_quota_rejects_before_creating_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(admission.LIMITS, "agent_runs_daily", 0)
    response = client.post("/agent-runs", json={"task": "pianifica i ritiri"}, headers=auth("demo-dk-coordinator"))
    assert response.status_code == 429 and response.headers["Retry-After"] == "3600"


def test_oversized_body_is_refused_before_parsing() -> None:
    response = client.post("/agent-runs", content=b"x" * (admission.LIMITS["body_bytes"] + 1),
                           headers=auth("demo-it-coordinator") | {"Content-Type": "application/json"})
    assert response.status_code == 413


def test_local_login_lists_demo_users_and_mints_tokens() -> None:
    users = client.get("/dev/users").json()
    assert {"subject": "demo-it-donor", "role": "donor"} in users
    token = client.post("/dev/token", json={"subject": "demo-it-donor"}).json()["access_token"]
    assert client.get("/offers", headers={"Authorization": f"Bearer {token}"}).status_code == 200


# --- the database refuses what the API role must never do, whatever the code does ---

def _as_app(tenant: uuid.UUID, role: str, subject: str, sql: str, params: dict | None = None) -> None:
    with tenant_transaction(tenant, role, subject) as session:
        session.execute(text(sql), params or {})


@pytest.mark.parametrize(
    ("role", "sql"),
    [
        ("org_admin", "UPDATE tenant SET status = 'suspended'"),
        ("org_admin", "UPDATE membership SET role = 'platform_admin' WHERE subject = 'demo-it-coordinator'"),
        ("org_admin", "UPDATE membership SET status = 'suspended' WHERE subject = 'demo-it-admin'"),
        ("coordinator", "UPDATE membership SET status = 'active' WHERE subject = 'demo-it-donor'"),
        ("registrant", "INSERT INTO membership (subject, role, status) VALUES ('demo-it-admin', 'donor', 'pending')"),
        ("registrant", "INSERT INTO membership (subject, role, status) VALUES ('demo-it-admin', 'coordinator', 'pending')"),
        ("registrant", "INSERT INTO organization (name, kind, status) VALUES ('Fake', 'donor', 'active')"),
    ],
    ids=["self-activate-network", "escalate-to-platform", "self-decide", "non-admin-decides",
         "register-someone-else", "self-register-coordinator", "active-organization"],
)
def test_database_guards_refuse_privilege_changes(role: str, sql: str) -> None:
    actor = "demo-it-admin" if role == "org_admin" else "demo-it-coordinator" if role == "coordinator" else "intruder-1"
    with pytest.raises(DBAPIError):
        _as_app(TENANT_IT, role, actor, sql)


def test_registration_cannot_create_an_active_network() -> None:
    tenant = uuid.uuid4()
    with pytest.raises(DBAPIError, match="row-level security"):
        _as_app(tenant, "registrant", "intruder-2",
                "INSERT INTO tenant (id, name, country, status, kind) VALUES (:id, 'Fake', 'IT', 'active', 'network')",
                {"id": tenant})


def test_directory_exposes_only_public_columns() -> None:
    with tenant_transaction(TENANT_DK, "donor", "demo-dk-donor") as session:
        columns = list(session.execute(text("SELECT * FROM network_directory LIMIT 1")).keys())
        queue = session.execute(text("SELECT count(*) FROM network_registration_queue")).scalar_one()
    assert columns == ["id", "name", "country"]
    assert queue == 0  # only a platform_admin transaction sees pending networks
