"""ADR-013: deterministic assignment, tenant opt-in, kill switch, no experiments on allocation."""

import json
from collections import Counter

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from secondchance.identity import Claims
from secondchance.db import tenant_transaction
from secondchance.experiments import assign, bucket, choose, erase_subject
from secondchance.seed import TENANT_IT

VARIANTS = [{"name": "control", "weight": 50}, {"name": "v2", "weight": 50}]
ALICE = Claims(sub="alice", tenant_id=TENANT_IT, role="coordinator")


@pytest.fixture
def experiment(owner):
    owner.execute(
        text(
            "INSERT INTO experiment (key, surface, unit, variants, status, hypothesis, primary_metric)"
            " VALUES ('prompt.knowledge-v2', 'prompt', 'subject', CAST(:variants AS jsonb), 'running',"
            " 'v2 cites sources more often', 'citation_correctness')"
        ),
        {"variants": json.dumps(VARIANTS)},
    )
    owner.execute(text("UPDATE tenant SET experiments_enabled = true WHERE id = :t"), {"t": TENANT_IT})
    yield "prompt.knowledge-v2"
    owner.execute(text("UPDATE tenant SET experiments_enabled = false WHERE id = :t"), {"t": TENANT_IT})
    owner.execute(text("DELETE FROM experiment_exposure WHERE experiment_key = 'prompt.knowledge-v2'"))
    owner.execute(text("DELETE FROM experiment WHERE key = 'prompt.knowledge-v2'"))


def test_assignment_is_deterministic_and_follows_weights() -> None:
    assert bucket("k", "alice") == bucket("k", "alice")
    split = Counter(choose([{"name": "a", "weight": 80}, {"name": "b", "weight": 20}], bucket("k", f"u{i}"))
                    for i in range(10_000))
    assert abs(split["a"] / 10_000 - 0.8) < 0.02


def test_running_experiment_assigns_and_records_exposure(experiment) -> None:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        first = assign(session, experiment, ALICE, "exp-test")
        second = assign(session, experiment, ALICE, "exp-test")
        exposures = session.execute(
            text("SELECT count(*) FROM experiment_exposure WHERE experiment_key = :k"), {"k": experiment}
        ).scalar_one()
    assert first == second == choose(VARIANTS, bucket(experiment, "alice"))
    assert exposures == 2


def test_kill_switch_and_opt_out_return_control(experiment, owner) -> None:
    owner.execute(text("UPDATE experiment SET status = 'stopped' WHERE key = :k"), {"k": experiment})
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        assert all(
            assign(session, experiment, Claims(sub=f"u{i}", tenant_id=TENANT_IT, role="coordinator"), "x") == "control"
            for i in range(50)
        )
    owner.execute(text("UPDATE experiment SET status = 'running' WHERE key = :k"), {"k": experiment})
    owner.execute(text("UPDATE tenant SET experiments_enabled = false WHERE id = :t"), {"t": TENANT_IT})
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        assert assign(session, experiment, ALICE, "x") == "control"


def test_unknown_experiment_returns_none() -> None:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        assert assign(session, "does-not-exist", ALICE, "x") is None


def test_allocation_can_never_be_an_experiment_surface(owner) -> None:
    with pytest.raises(IntegrityError):
        owner.execute(
            text(
                "INSERT INTO experiment (key, surface, unit, variants, hypothesis, primary_metric)"
                " VALUES ('alloc', 'allocation', 'tenant', CAST(:variants AS jsonb), 'h', 'm')"
            ),
            {"variants": json.dumps(VARIANTS)},
        )


def test_app_role_cannot_define_experiments() -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_transaction(TENANT_IT, "platform_admin") as session:
            session.execute(text("DELETE FROM experiment"))


def test_erasure_removes_a_subjects_exposures(experiment, maintenance_engine) -> None:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        assign(session, experiment, ALICE, "x")
    with maintenance_engine.begin() as connection:
        assert erase_subject(connection, TENANT_IT, "alice") >= 1
