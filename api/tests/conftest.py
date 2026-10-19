"""Tests run against the Compose stack: `secondchance_test` database, ElasticMQ, SeaweedFS.

The defaults match docker-compose.yml; SECONDCHANCE_TEST_* variables override them. Endpoints and
credentials are always forced to local values, so a test can never reach AWS.
Every session starts from an empty schema: downgrade to base, upgrade to head, seed.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

# 127.0.0.1, not localhost: with Docker Desktop on Windows, ::1:5432 hangs instead of refusing.
TEST_DB = "127.0.0.1:5432/secondchance_test"
ROLES = {
    "SECONDCHANCE_DATABASE_URL": "secondchance_app:app-local-only",
    "SECONDCHANCE_MIGRATOR_URL": "secondchance_migrator:migrator-local-only",
    "SECONDCHANCE_MAINTENANCE_URL": "secondchance_maintenance:maintenance-local-only",
}
for var, credentials in ROLES.items():
    os.environ[var] = os.environ.get(var.replace("SECONDCHANCE_", "SECONDCHANCE_TEST_"), f"postgresql+psycopg://{credentials}@{TEST_DB}")
    # The session fixture drops every table: refuse anything that is not a test database.
    assert os.environ[var].endswith("_test"), f"{var} must point to a *_test database"

os.environ.update(
    {
        "SECONDCHANCE_JWT_SECRET": "test-only-secret-0123456789abcdef0123",
        "SECONDCHANCE_ENV": "local",
        "AWS_REGION": "eu-central-1",
        "AWS_ACCESS_KEY_ID": "local",
        "AWS_SECRET_ACCESS_KEY": "local",
        "SECONDCHANCE_SQS_ENDPOINT": os.environ.get("SECONDCHANCE_TEST_SQS_ENDPOINT", "http://127.0.0.1:9324"),
        "SECONDCHANCE_S3_ENDPOINT": os.environ.get("SECONDCHANCE_TEST_S3_ENDPOINT", "http://127.0.0.1:8333"),
        "SECONDCHANCE_S3_BUCKET": "secondchance-test",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    }
)
os.environ.pop("SECONDCHANCE_ROUTER_SHADOW_URL", None)  # tests wire the shadow router explicitly

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Connection, create_engine, text  # noqa: E402

from secondchance.db import tenant_transaction  # noqa: E402
from secondchance.seed import TENANT_IT, _id, seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def fresh_database() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    seed()


@pytest.fixture(scope="session", autouse=True)
def object_storage_ready() -> None:
    """SeaweedFS allocates volumes on the first write to a new bucket and may answer 5xx
    for a few seconds right after `docker compose up`: wait for one real round trip."""
    import time

    from secondchance import storage

    s3, deadline = storage.client(), time.monotonic() + 60
    while True:
        try:
            storage.ensure_bucket(s3)
            s3.put_object(Bucket=storage.bucket(), Key="warm-up", Body=b"ok")
            if s3.get_object(Bucket=storage.bucket(), Key="warm-up")["Body"].read() == b"ok":
                return
        except Exception:
            if time.monotonic() > deadline:
                raise
        time.sleep(1)


@pytest.fixture(scope="session")
def migrator_engine():
    engine = create_engine(os.environ["SECONDCHANCE_MIGRATOR_URL"])
    yield engine
    engine.dispose()


@pytest.fixture
def owner(migrator_engine) -> Iterator[Connection]:
    """Table owner, outside RLS, autocommit: only for arranging state the app cannot create."""
    with migrator_engine.connect() as connection:
        connection.execution_options(isolation_level="AUTOCOMMIT")
        yield connection


@pytest.fixture(autouse=True)
def close_open_runs(migrator_engine) -> Iterator[None]:
    """Runs a test left queued would count against the per-network quota (ADR-016)."""
    yield
    with migrator_engine.begin() as connection:
        connection.execute(text("UPDATE agent_run SET status = 'cancelled' WHERE status IN ('queued', 'running')"))
        # One matching run at a time per network (ADR-016): a run a test left queued would block the next.
        connection.execute(text("UPDATE matching_run SET status = 'failed', error_category = 'test_cleanup'"
                                " WHERE status IN ('queued', 'running')"))


@pytest.fixture(scope="session")
def maintenance_engine():
    engine = create_engine(os.environ["SECONDCHANCE_MAINTENANCE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture
def available_offer() -> uuid.UUID:
    """A new available offer in the IT tenant, inserted through the app role."""
    with tenant_transaction(TENANT_IT, "donor") as session:
        return session.execute(
            text(
                "INSERT INTO donation_offer (donor_id, category, quantity, unit, date_kind,"
                " expires_on, storage, pickup_from, pickup_until, status)"
                " VALUES (:donor, 'bread', 5, 'kg', 'best_before', current_date + 3, 'ambient',"
                " now(), now() + interval '2 hours', 'available') RETURNING id"
            ),
            {"donor": _id("it/org/donor")},
        ).scalar_one()
