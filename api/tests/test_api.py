"""FR-001, FR-002, ADR-003, ADR-017 end to end: token -> membership -> SET LOCAL -> RLS."""

import time
import uuid
from datetime import UTC, date, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from secondchance.auth import AUDIENCE, ISSUER, SECRET, mint_token
from secondchance.main import app
from secondchance.seed import TENANT_DK, TENANT_IT

client = TestClient(app)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(subject)}"}


def _token(key: str = SECRET, algorithm: str = "HS256", **overrides: object) -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "demo-it-coordinator", "iat": now, "exp": now + 60} | overrides
    return jwt.encode(claims, key, algorithm=algorithm)


def test_missing_token_is_unauthorized() -> None:
    assert client.get("/offers").status_code == 401


@pytest.mark.parametrize(
    "token",
    [
        _token(exp=int(time.time()) - 10),
        _token(key="another-key-0123456789abcdef0123456789"),
        _token(aud="someone-else"),
        _token(iss="https://evil.example"),
        _token(sub=5),
        _token(sub=""),
        _token(key=None, algorithm="none"),
        "garbage",
    ],
    ids=["expired", "wrong-key", "wrong-audience", "wrong-issuer", "numeric-sub", "empty-sub", "alg-none", "garbage"],
)
def test_invalid_token_is_unauthorized(token: str) -> None:
    assert client.get("/offers", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_claims_cannot_choose_tenant_or_role() -> None:
    # A forged tenant_id/role claim is ignored: the membership decides (ADR-017).
    token = _token(sub="demo-it-donor", tenant_id=str(TENANT_DK), role="platform_admin")
    offers = client.get("/offers", headers={"Authorization": f"Bearer {token}"}).json()
    assert {o["tenant_id"] for o in offers} == {str(TENANT_IT)}


def test_valid_token_without_membership_is_forbidden() -> None:
    assert client.get("/offers", headers=auth("nobody-registered")).status_code == 403


@pytest.mark.parametrize(("subject", "tenant"), [("demo-it-coordinator", TENANT_IT), ("demo-dk-coordinator", TENANT_DK)])
def test_offers_are_scoped_to_the_membership_tenant(subject: str, tenant: uuid.UUID) -> None:
    response = client.get("/offers", headers=auth(subject))
    assert response.status_code == 200
    assert {offer["tenant_id"] for offer in response.json()} == {str(tenant)}


def test_stale_version_gets_conflict(available_offer: uuid.UUID) -> None:
    url = f"/offers/{available_offer}/reserve"
    first = client.post(url, json={"version": 1}, headers=auth("demo-it-coordinator"))
    second = client.post(url, json={"version": 1}, headers=auth("demo-it-coordinator"))
    assert (first.status_code, first.json()["version"]) == (200, 2)
    assert second.status_code == 409


def test_other_tenant_cannot_reserve(available_offer: uuid.UUID) -> None:
    response = client.post(f"/offers/{available_offer}/reserve", json={"version": 1}, headers=auth("demo-dk-coordinator"))
    assert response.status_code == 409


def test_donor_cannot_reserve(available_offer: uuid.UUID) -> None:
    response = client.post(f"/offers/{available_offer}/reserve", json={"version": 1}, headers=auth("demo-it-donor"))
    assert response.status_code == 403


def _offer(**overrides) -> dict:
    start = datetime.now(UTC) + timedelta(hours=1)
    return {"category": "bakery", "quantity": "8.5", "unit": "kg", "date_kind": "best_before",
            "expires_on": (date.today() + timedelta(days=3)).isoformat(), "storage": "ambient",
            "pickup_from": start.isoformat(), "pickup_until": (start + timedelta(hours=4)).isoformat()} | overrides


def test_donor_creates_and_sees_only_its_own_offers() -> None:
    created = client.post("/offers", json=_offer(), headers=auth("demo-it-donor"))
    assert created.status_code == 201
    mine = client.get("/offers", headers=auth("demo-it-donor")).json()
    everything = client.get("/offers", headers=auth("demo-it-coordinator")).json()
    assert created.json()["id"] in {o["id"] for o in mine}
    assert len(everything) >= len(mine)


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": "0"},
        {"unit": "tons"},
        {"date_kind": "use_by", "expires_on": (date.today() - timedelta(days=1)).isoformat()},
        {"pickup_until": datetime.now(UTC).isoformat()},
        {"tenant_id": str(TENANT_DK)},
    ],
    ids=["zero-quantity", "unknown-unit", "expired-use-by", "window-backwards", "extra-field"],
)
def test_malformed_offers_are_rejected_before_the_database(bad: dict) -> None:
    assert client.post("/offers", json=_offer(**bad), headers=auth("demo-it-donor")).status_code == 422


def test_only_donors_create_offers() -> None:
    assert client.post("/offers", json=_offer(), headers=auth("demo-it-coordinator")).status_code == 403


def test_agent_run_is_accepted_processed_and_readable() -> None:
    from secondchance.agents.worker import drain
    from secondchance.queues import MemoryQueue
    from secondchance.routes.agents import agents_queue

    queue = MemoryQueue()
    app.dependency_overrides[agents_queue] = lambda: queue
    try:
        created = client.post("/agent-runs", json={"task": "Abbiamo 30 kg di frutta da donare"}, headers=auth("demo-it-coordinator"))
        assert created.status_code == 202
        drain(queue)
        run = client.get(f"/agent-runs/{created.json()['id']}", headers=auth("demo-it-coordinator")).json()
        other_tenant = client.get(f"/agent-runs/{created.json()['id']}", headers=auth("demo-dk-coordinator"))
    finally:
        app.dependency_overrides.clear()
    assert run["status"] == "succeeded"
    assert [s["agent"] for s in run["steps"]] == [
        "supervisor",
        "intake",
        "supervisor",
        "donation_operations",
        "supervisor",
        "compliance_review",
        "supervisor",
    ]
    assert "route:donation_offer:ok" in run["findings"]
    assert run["generated_by"] == "secondchance-agents"
    assert other_tenant.status_code == 404


@pytest.mark.parametrize("subject", ["demo-it-donor", "demo-it-volunteer"])
def test_only_coordinators_start_agent_runs(subject: str) -> None:
    assert client.post("/agent-runs", json={"task": "una prova"}, headers=auth(subject)).status_code == 403
