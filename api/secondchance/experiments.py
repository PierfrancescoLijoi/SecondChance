"""Feature flags and A/B experiments (ADR-013).

Assignment is a pure function of (experiment key, unit): every stateless instance computes
the same variant without storing assignments. Stopping an experiment, or a tenant that has
not opted in, sends everyone to the control variant (the first one).
"""

import hashlib
import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.principal import Claims
from secondchance.observability import meter
from secondchance.privacy import subject_hash

BUCKETS = 10_000

exposures_counter = meter.create_counter("secondchance.experiment.exposures", description="Exposures by experiment and variant")


def bucket(key: str, unit: str) -> int:
    return int(hashlib.sha256(f"{key}:{unit}".encode()).hexdigest()[:8], 16) % BUCKETS


def choose(variants: Sequence[dict], position: int) -> str:
    """Maps a bucket onto the cumulative weights; weights need not add up to 100."""
    total = sum(v["weight"] for v in variants)
    if total <= 0 or any(v["weight"] < 0 for v in variants):
        raise ValueError("variant weights must be non-negative with a positive sum")
    threshold = position / BUCKETS * total
    cumulative = 0.0
    for variant in variants:
        cumulative += variant["weight"]
        if threshold < cumulative:
            return variant["name"]
    return variants[-1]["name"]


def assign(session: Session, key: str, claims: Claims, correlation_id: str) -> str | None:
    """The caller's variant, recording an exposure when the experiment is live for them.

    Returns None when the experiment does not exist, so callers keep their default.
    """
    experiment = session.execute(
        text("SELECT unit, variants, status FROM experiment WHERE key = :key"), {"key": key}
    ).mappings().one_or_none()
    if experiment is None:
        return None
    control = experiment["variants"][0]["name"]
    enabled = session.execute(text("SELECT experiments_enabled FROM tenant")).scalar_one_or_none()
    if experiment["status"] != "running" or not enabled:
        return control

    unit = claims.sub if experiment["unit"] == "subject" else str(claims.tenant_id)
    variant = choose(experiment["variants"], bucket(key, unit))
    session.execute(
        text(
            "INSERT INTO experiment_exposure (experiment_key, variant, unit_hash, correlation_id)"
            " VALUES (:key, :variant, :unit_hash, :cid)"
        ),
        {"key": key, "variant": variant, "unit_hash": _unit_hash(claims, experiment["unit"]), "cid": correlation_id},
    )
    exposures_counter.add(1, {"experiment": key, "variant": variant})
    return variant


def _unit_hash(claims: Claims, unit: str) -> str:
    if unit == "subject":
        return subject_hash(claims.tenant_id, claims.sub)
    return hashlib.sha256(str(claims.tenant_id).encode()).hexdigest()


def erase_subject(session: Session, tenant_id: uuid.UUID, subject: str) -> int:
    """GDPR erasure (ADR-014): drops a subject's exposures. Runs as secondchance_maintenance."""
    return session.execute(
        text("DELETE FROM experiment_exposure WHERE tenant_id = :tenant AND unit_hash = :hash"),
        {"tenant": tenant_id, "hash": subject_hash(tenant_id, subject)},
    ).rowcount
