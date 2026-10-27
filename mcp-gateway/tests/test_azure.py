"""Azure adapters of the gateway (ADR-023): Table Storage rate limit and Entra service tokens, against fakes."""

import time

import jwt
import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcp_gateway.policy import PolicyDenied, TableRateLimiter
from mcp_gateway.service_auth import require_service_role, verify_service_token

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-0000-0000-0000-000000000002"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeEntity(dict):
    metadata: dict


class FakeTable:
    """Just enough of TableClient: create/get/update with ETags and the query the purge uses."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], tuple[dict, int]] = {}
        self.conflicts_to_inject = 0

    def get_entity(self, partition, row):
        if (partition, row) not in self.rows:
            raise ResourceNotFoundError("missing")
        data, version = self.rows[(partition, row)]
        entity = FakeEntity(data)
        entity.metadata = {"etag": str(version)}
        return entity

    def create_entity(self, entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise ResourceExistsError("exists")
        self.rows[key] = (dict(entity), 1)

    def update_entity(self, entity, mode, etag, match_condition):
        assert mode == "replace" and match_condition == MatchConditions.IfNotModified
        key = (entity["PartitionKey"], entity["RowKey"])
        if self.conflicts_to_inject:
            self.conflicts_to_inject -= 1
            raise ResourceModifiedError("etag")
        data, version = self.rows[key]
        if str(version) != etag:
            raise ResourceModifiedError("etag")
        self.rows[key] = (dict(entity), version + 1)

    def query_entities(self, query_filter, parameters):
        limit = parameters["limit"]
        return [dict(data) for (partition, _), (data, _) in list(self.rows.items()) if partition < limit]

    def delete_entity(self, partition, row):
        del self.rows[(partition, row)]


def test_table_limiter_allows_up_to_the_limit_then_denies() -> None:
    limiter = TableRateLimiter(FakeTable())
    for _ in range(3):
        limiter.consume("tenant:subject:knowledge_search", 3)
    with pytest.raises(PolicyDenied):
        limiter.consume("tenant:subject:knowledge_search", 3)
    limiter.consume("tenant:other:knowledge_search", 3)  # another caller has its own window


def test_table_limiter_retries_a_lost_race_instead_of_double_counting() -> None:
    table = FakeTable()
    limiter = TableRateLimiter(table)
    limiter.consume("k", 5)
    table.conflicts_to_inject = 2  # two concurrent writers won the ETag first
    limiter.consume("k", 5)
    (data, _), = table.rows.values()
    assert data["requests"] == 2


def test_table_limiter_refuses_when_contention_never_clears() -> None:
    table = FakeTable()
    limiter = TableRateLimiter(table)
    limiter.consume("k", 5)
    table.conflicts_to_inject = 99
    with pytest.raises(PolicyDenied):
        limiter.consume("k", 5)


def test_table_limiter_purges_old_windows_only() -> None:
    table = FakeTable()
    limiter = TableRateLimiter(table)
    current = str(int(time.time()) // 60)
    table.rows[("1", "old")] = ({"PartitionKey": "1", "RowKey": "old", "requests": 1}, 1)
    table.rows[(current, "now")] = ({"PartitionKey": current, "RowKey": "now", "requests": 1}, 1)
    assert limiter.purge() == 1 and list(table.rows) == [(current, "now")]


def token(**claims) -> str:
    now = int(time.time())
    base = {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": f"api://{CLIENT}", "iat": now,
            "exp": now + 600, "roles": ["Tool.Invoke"]}
    return jwt.encode({**base, **claims}, KEY, algorithm="RS256", headers={"kid": "k"})


def test_only_a_token_with_the_invoke_role_passes() -> None:
    ok = {"tenant_id": TENANT, "client_id": CLIENT, "role": "Tool.Invoke", "key": KEY.public_key()}
    assert verify_service_token(token(), **ok)
    for bad in (token(roles=["Tool.Execute"]), token(aud="api://other"), token(scp="access_as_user"), token(exp=1)):
        with pytest.raises(jwt.PyJWTError):
            verify_service_token(bad, **ok)


def test_the_dependency_is_inert_until_configured_and_closed_after(monkeypatch) -> None:
    app = FastAPI()

    @app.get("/x", dependencies=[__import__("fastapi").Depends(require_service_role("Tool.Invoke"))])
    def x() -> dict:
        return {"ok": True}

    client = TestClient(app)
    monkeypatch.delenv("SECONDCHANCE_SERVICE_AUTH_AUDIENCE", raising=False)
    assert client.get("/x").status_code == 200  # AWS and Compose: unchanged
    monkeypatch.setenv("SECONDCHANCE_SERVICE_AUTH_AUDIENCE", CLIENT)
    monkeypatch.setenv("SECONDCHANCE_ENTRA_TENANT_ID", TENANT)
    assert client.get("/x").status_code == 401
    assert client.get("/x", headers={"Authorization": "Bearer garbage"}).status_code == 401
