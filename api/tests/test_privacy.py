"""ADR-014: every column is classified, free text is redacted, pseudonyms are stable."""

import uuid

import pytest

from secondchance.db import SessionLocal
from secondchance.privacy import PII_CLASSES, inventory, redact, subject_hash


def test_every_column_is_classified() -> None:
    # A migration that adds a column without `COMMENT ON COLUMN ... 'pii:...'` fails here.
    with SessionLocal() as session:
        columns = inventory(session)
    unclassified = [f"{c['table']}.{c['column']}" for c in columns if c["pii"] not in PII_CLASSES or not c["purpose"]]
    assert len(columns) > 50
    assert unclassified == []


def test_inventory_marks_pseudonyms_as_personal() -> None:
    with SessionLocal() as session:
        classes = {(c["table"], c["column"]): c["pii"] for c in inventory(session)}
    assert classes[("audit_event", "actor")] == "personal"
    assert classes[("agent_memory", "content")] == "personal"
    assert classes[("donation_offer", "quantity")] == "none"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("scrivete a mario.rossi@example.org", "scrivete a [EMAIL]"),
        ("chiamami al +39 333 123 4567 domani", "chiamami al [PHONE] domani"),
        ("ring 20 12 34 56 i morgen", "ring [PHONE] i morgen"),
        ("IBAN IT60 X054 2811 1010 0000 0123 456 grazie", "IBAN [IBAN] grazie"),
        ("konto DK5000400440116243", "konto [IBAN]"),
    ],
)
def test_redact_removes_contacts(raw: str, expected: str) -> None:
    assert redact(raw) == expected


@pytest.mark.parametrize(
    "harmless",
    ["40 kg di pasta entro il 2026-10-17", "afhentning 17.10.2026 kl. 14", "ordine 12 casse, 3 pallet"],
)
def test_redact_keeps_dates_and_quantities(harmless: str) -> None:
    assert redact(harmless) == harmless


def test_subject_hash_is_stable_and_tenant_scoped() -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    assert subject_hash(tenant_a, "sub-1") == subject_hash(tenant_a, "sub-1")
    assert subject_hash(tenant_a, "sub-1") != subject_hash(tenant_b, "sub-1")
    assert len(subject_hash(tenant_a, "sub-1")) == 64
