"""ADR-012: correlation IDs end to end, redacted structured logs, telemetry off without endpoint."""

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from secondchance.auth import mint_token
from secondchance.db import tenant_transaction
from secondchance.main import app
from secondchance.observability import JsonFormatter, RedactingFilter, configure_telemetry, correlation_id
from secondchance.seed import TENANT_IT

client = TestClient(app)


def test_correlation_id_is_echoed_or_minted() -> None:
    echoed = client.get("/health", headers={"X-Correlation-ID": "req-123"})
    minted = client.get("/health", headers={"X-Correlation-ID": "bad id with spaces"})
    assert echoed.headers["x-correlation-id"] == "req-123"
    assert minted.headers["x-correlation-id"] not in ("", "bad id with spaces")


def test_correlation_id_reaches_the_audit_log(available_offer) -> None:
    token = mint_token("demo-it-coordinator")
    response = client.post(
        f"/offers/{available_offer}/reserve",
        json={"version": 1},
        headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": "audit-cid-42"},
    )
    assert response.status_code == 200
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        cid = session.execute(
            text("SELECT correlation_id FROM audit_event WHERE object_id = :id"), {"id": available_offer}
        ).scalar_one()
    assert cid == "audit-cid-42"


def test_log_lines_are_json_redacted_and_correlated() -> None:
    record = logging.LogRecord("secondchance.test", logging.INFO, __file__, 1, "contact %s", ("mario@example.org",), None)
    token = correlation_id.set("log-cid")
    try:
        RedactingFilter().filter(record)
        line = json.loads(JsonFormatter().format(record))
    finally:
        correlation_id.reset(token)
    assert line["message"] == "contact [EMAIL]"
    assert line["correlation_id"] == "log-cid"
    assert line["level"] == "INFO"


def test_exceptions_lose_their_stack_and_personal_data() -> None:
    try:
        raise ValueError("bad input from mario@example.org")
    except ValueError:
        import sys

        record = logging.LogRecord("secondchance.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    RedactingFilter().filter(record)
    assert record.exc_info is None
    assert record.error == "ValueError: bad input from [EMAIL]"


def test_telemetry_stays_off_without_an_endpoint() -> None:
    assert configure_telemetry(FastAPI(), None) is False
