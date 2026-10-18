"""Synthetic networks, users and offers for demos and tests (PRD 8.1). Safe to run repeatedly.

Runs as secondchance_migrator: creating tenants is platform provisioning, outside any tenant.
"""

import os
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from secondchance.dbconn import make_engine

NAMESPACE = uuid.UUID("5d6c1a52-0d5e-4c35-9a0f-3f1f3c2a0001")


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


TENANT_IT = _id("tenant/it")
TENANT_DK = _id("tenant/dk")
TENANT_PLATFORM = _id("tenant/platform")  # public knowledge and platform admins (ADR-015, ADR-017)

# Synthetic subjects with active memberships, for the local login page and the tests.
DEMO_USERS: list[dict] = [
    {"subject": "demo-platform-admin", "tenant": TENANT_PLATFORM, "role": "platform_admin", "org": None},
    {"subject": "demo-it-admin", "tenant": TENANT_IT, "role": "org_admin", "org": "it/org/ngo"},
    {"subject": "demo-it-coordinator", "tenant": TENANT_IT, "role": "coordinator", "org": "it/org/ngo"},
    {"subject": "demo-it-donor", "tenant": TENANT_IT, "role": "donor", "org": "it/org/donor"},
    {"subject": "demo-it-volunteer", "tenant": TENANT_IT, "role": "volunteer", "org": "it/org/ngo"},
    {"subject": "demo-dk-admin", "tenant": TENANT_DK, "role": "org_admin", "org": "dk/org/ngo"},
    {"subject": "demo-dk-coordinator", "tenant": TENANT_DK, "role": "coordinator", "org": "dk/org/ngo"},
    {"subject": "demo-dk-donor", "tenant": TENANT_DK, "role": "donor", "org": "dk/org/donor"},
]

TENANTS = [
    {"id": TENANT_IT, "key": "it", "name": "Rete Solidale Torino (sintetico)", "country": "IT",
     "ngo": "Banco Alimentare Demo", "donor": "Supermercato Demo", "center": "Centro Demo Aurora"},
    {"id": TENANT_DK, "key": "dk", "name": "Fødevarenetværk København (syntetisk)", "country": "DK",
     "ngo": "Fødevarebank Demo", "donor": "Demo Supermarked", "center": "Demo Center Nørrebro"},
]


def _rows(today: date) -> dict[str, list[dict]]:
    pickup = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    rows: dict[str, list[dict]] = {"tenant": [], "organization": [], "center": [], "offer": []}
    for t in TENANTS:
        key, tid = t["key"], t["id"]
        ngo, donor = _id(f"{key}/org/ngo"), _id(f"{key}/org/donor")
        rows["tenant"].append({"id": tid, "name": t["name"], "country": t["country"], "kind": "network"})
        rows["organization"] += [
            {"id": ngo, "tenant_id": tid, "name": t["ngo"], "kind": "ngo", "donor_type": None},
            {"id": donor, "tenant_id": tid, "name": t["donor"], "kind": "donor", "donor_type": "supermarket"},
        ]
        rows["center"].append(
            {"id": _id(f"{key}/center/1"), "tenant_id": tid, "organization_id": ngo, "name": t["center"]}
        )
        rows["offer"] += [
            {"id": _id(f"{key}/offer/yogurt"), "tenant_id": tid, "donor_id": donor,
             "category": "dairy", "quantity": 12, "unit": "kg", "date_kind": "use_by",
             "expires_on": today + timedelta(days=2), "storage": "chilled",
             "pickup_from": pickup, "pickup_until": pickup + timedelta(hours=3)},
            {"id": _id(f"{key}/offer/pasta"), "tenant_id": tid, "donor_id": donor,
             "category": "dry_goods", "quantity": 40, "unit": "kg", "date_kind": "best_before",
             "expires_on": today + timedelta(days=60), "storage": "ambient",
             "pickup_from": pickup, "pickup_until": pickup + timedelta(hours=6)},
        ]
    rows["tenant"].append({"id": TENANT_PLATFORM, "name": "SecondChance platform", "country": "EU", "kind": "platform"})
    rows["membership"] = [
        {"id": _id(f"membership/{u['subject']}"), "subject": u["subject"], "tenant_id": u["tenant"],
         "organization_id": _id(u["org"]) if u["org"] else None, "role": u["role"]}
        for u in DEMO_USERS
    ]
    return rows


def seed(url: str | None = None) -> None:
    rows = _rows(date.today())
    engine = make_engine(url or os.environ["SECONDCHANCE_MIGRATOR_URL"])
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenant (id, name, country, kind, status) VALUES (:id, :name, :country, :kind, 'active')"
                 " ON CONFLICT (id) DO NOTHING"),
            rows["tenant"],
        )
        conn.execute(
            text("INSERT INTO organization (id, tenant_id, name, kind, donor_type)"
                 " VALUES (:id, :tenant_id, :name, :kind, :donor_type) ON CONFLICT (id) DO NOTHING"),
            rows["organization"],
        )
        conn.execute(
            text("INSERT INTO center (id, tenant_id, organization_id, name)"
                 " VALUES (:id, :tenant_id, :organization_id, :name) ON CONFLICT (id) DO NOTHING"),
            rows["center"],
        )
        conn.execute(
            text("INSERT INTO donation_offer (id, tenant_id, donor_id, category, quantity, unit,"
                 " date_kind, expires_on, storage, pickup_from, pickup_until, status)"
                 " VALUES (:id, :tenant_id, :donor_id, :category, :quantity, :unit, :date_kind,"
                 " :expires_on, :storage, :pickup_from, :pickup_until, 'available')"
                 " ON CONFLICT (id) DO NOTHING"),
            rows["offer"],
        )
        conn.execute(
            text("INSERT INTO membership (id, subject, tenant_id, organization_id, role, status)"
                 " VALUES (:id, :subject, :tenant_id, :organization_id, :role, 'active') ON CONFLICT (id) DO NOTHING"),
            rows["membership"],
        )
        from secondchance.knowledge.sample import spaces_rows  # sample imports this module

        conn.execute(
            text("INSERT INTO knowledge_space (id, tenant_id, name, kind, visibility, allowed_roles)"
                 " VALUES (:id, :tenant_id, :name, :kind, :visibility, :allowed_roles) ON CONFLICT (id) DO NOTHING"),
            spaces_rows(),
        )
    engine.dispose()


if __name__ == "__main__":
    seed()
    print(f"seeded tenants: IT={TENANT_IT} DK={TENANT_DK}")
