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
    {"subject": "demo-it-admin", "tenant": TENANT_IT, "role": "org_admin", "org": "it/org/ngo", "name": "Admin Demo"},
    {"subject": "demo-it-coordinator", "tenant": TENANT_IT, "role": "coordinator", "org": "it/org/ngo",
     "name": "Coordinatrice Demo"},
    {"subject": "demo-it-donor", "tenant": TENANT_IT, "role": "donor", "org": "it/org/donor"},
    {"subject": "demo-it-volunteer", "tenant": TENANT_IT, "role": "volunteer", "org": "it/org/ngo", "name": "Volontario Demo"},
    {"subject": "demo-it-center", "tenant": TENANT_IT, "role": "center_staff", "org": "it/org/ngo",
     "center": "it/center/1", "name": "Staff Centro Aurora"},
    {"subject": "demo-dk-admin", "tenant": TENANT_DK, "role": "org_admin", "org": "dk/org/ngo", "name": "Demo Admin"},
    {"subject": "demo-dk-coordinator", "tenant": TENANT_DK, "role": "coordinator", "org": "dk/org/ngo",
     "name": "Demo Koordinator"},
    {"subject": "demo-dk-donor", "tenant": TENANT_DK, "role": "donor", "org": "dk/org/donor"},
    {"subject": "demo-dk-volunteer", "tenant": TENANT_DK, "role": "volunteer", "org": "dk/org/ngo", "name": "Demo Frivillig"},
    {"subject": "demo-dk-center", "tenant": TENANT_DK, "role": "center_staff", "org": "dk/org/ngo",
     "center": "dk/center/1", "name": "Demo Centerpersonale"},
]

ALL_CATEGORIES = ["dairy", "meat_fish", "fruit_vegetables", "bakery", "dry_goods", "frozen", "ready_meals",
                  "beverages", "other"]
DAILY = [(day, "07:00", "22:00") for day in range(1, 8)]
WEEKDAYS = [(day, "09:00", "19:00") for day in range(1, 7)]

# Synthetic centres near each network's donor (PRD 8.1): two per network, with different capabilities,
# so the solver has real choices to explain. Coordinates are public city locations, not addresses of people.
TENANTS = [
    {"id": TENANT_IT, "key": "it", "name": "Rete Solidale Torino (sintetico)", "country": "IT",
     "ngo": "Banco Alimentare Demo", "donor": "Supermercato Demo", "donor_location": (45.0703, 7.6869),
     "centers": [
         {"key": "1", "name": "Centro Demo Aurora", "address": "Via Demo 1, Torino", "location": (45.0861, 7.6858),
          "timezone": "Europe/Rome", "storage": ["ambient", "chilled"], "capacity": 300, "slots": DAILY},
         {"key": "2", "name": "Emporio Solidale Demo", "address": "Corso Demo 20, Torino", "location": (45.0522, 7.6633),
          "timezone": "Europe/Rome", "storage": ["ambient"], "capacity": 150, "slots": WEEKDAYS},
     ]},
    {"id": TENANT_DK, "key": "dk", "name": "Fødevarenetværk København (syntetisk)", "country": "DK",
     "ngo": "Fødevarebank Demo", "donor": "Demo Supermarked", "donor_location": (55.6761, 12.5683),
     "centers": [
         {"key": "1", "name": "Demo Center Nørrebro", "address": "Demovej 1, København N", "location": (55.6942, 12.5476),
          "timezone": "Europe/Copenhagen", "storage": ["ambient", "chilled", "frozen"], "capacity": 250, "slots": DAILY},
         {"key": "2", "name": "Demo Center Amager", "address": "Demogade 2, København S", "location": (55.6596, 12.6012),
          "timezone": "Europe/Copenhagen", "storage": ["ambient"], "capacity": 120, "slots": WEEKDAYS},
     ]},
]


def _rows(today: date) -> dict[str, list[dict]]:
    pickup = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    rows: dict[str, list[dict]] = {"tenant": [], "organization": [], "center": [], "slot": [], "offer": []}
    for t in TENANTS:
        key, tid = t["key"], t["id"]
        ngo, donor = _id(f"{key}/org/ngo"), _id(f"{key}/org/donor")
        rows["tenant"].append({"id": tid, "name": t["name"], "country": t["country"], "kind": "network"})
        rows["organization"] += [
            {"id": ngo, "tenant_id": tid, "name": t["ngo"], "kind": "ngo", "donor_type": None,
             "lat": None, "lon": None},
            {"id": donor, "tenant_id": tid, "name": t["donor"], "kind": "donor", "donor_type": "supermarket",
             "lat": t["donor_location"][0], "lon": t["donor_location"][1]},
        ]
        for c in t["centers"]:
            center_id = _id(f"{key}/center/{c['key']}")
            rows["center"].append(
                {"id": center_id, "tenant_id": tid, "organization_id": ngo, "name": c["name"], "address": c["address"],
                 "lat": c["location"][0], "lon": c["location"][1], "timezone": c["timezone"],
                 "categories": ALL_CATEGORIES, "storage": c["storage"], "capacity": c["capacity"]}
            )
            rows["slot"] += [
                {"tenant_id": tid, "center_id": center_id, "weekday": day, "opens": opens, "closes": closes}
                for day, opens, closes in c["slots"]
            ]
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
         "organization_id": _id(u["org"]) if u["org"] else None, "role": u["role"],
         "center_id": _id(u["center"]) if u.get("center") else None, "display_name": u.get("name")}
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
        # Coordinates only where none were set: an admin's later change survives a re-seed.
        conn.execute(
            text("UPDATE organization SET location = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography"
                 " WHERE id = :id AND location IS NULL AND CAST(:lat AS float8) IS NOT NULL"),
            rows["organization"],
        )
        conn.execute(
            text("INSERT INTO center (id, tenant_id, organization_id, name, address, location, timezone,"
                 " accepted_categories, storage_capabilities, daily_capacity_kg)"
                 " VALUES (:id, :tenant_id, :organization_id, :name, :address,"
                 " ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :timezone, :categories, :storage, :capacity)"
                 " ON CONFLICT (id) DO UPDATE SET address = EXCLUDED.address, location = EXCLUDED.location,"
                 " timezone = EXCLUDED.timezone, storage_capabilities = EXCLUDED.storage_capabilities,"
                 " daily_capacity_kg = EXCLUDED.daily_capacity_kg"
                 " WHERE center.location IS NULL AND NOT EXISTS (SELECT 1 FROM center_slot s WHERE s.center_id = center.id)"),
            rows["center"],
        )
        conn.execute(
            text("INSERT INTO center_slot (tenant_id, center_id, weekday, opens, closes)"
                 " SELECT :tenant_id, :center_id, :weekday, CAST(:opens AS time), CAST(:closes AS time)"
                 " WHERE NOT EXISTS (SELECT 1 FROM center_slot s WHERE s.center_id = :center_id AND s.weekday = :weekday)"),
            rows["slot"],
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
            text("INSERT INTO membership (id, subject, tenant_id, organization_id, role, status, center_id, display_name)"
                 " VALUES (:id, :subject, :tenant_id, :organization_id, :role, 'active', :center_id, :display_name)"
                 " ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name, center_id = EXCLUDED.center_id"
                 " WHERE membership.display_name IS NULL"),
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
