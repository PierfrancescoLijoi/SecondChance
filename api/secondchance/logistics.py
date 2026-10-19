"""Shared logistics vocabulary: categories, storage, load estimates (FR-011, FR-012, FR-014).

Capacities are in kg. Litres count as kg; pieces as half a kilo each until offers carry their
own weights. SQL aggregates spell the same factors as
`quantity * CASE unit WHEN 'pcs' THEN 0.5 ELSE 1 END` (no SQL is built from strings, S608);
tests/test_operations.py checks that both stay equal, so the solver, the approval check and the
dashboard never disagree about how full a centre is.
"""

CATEGORIES = ("dairy", "meat_fish", "fruit_vegetables", "bakery", "dry_goods", "frozen", "ready_meals", "beverages", "other")
STORAGE = ("ambient", "chilled", "frozen")
LOAD_FACTOR = {"kg": 1.0, "l": 1.0, "pcs": 0.5}

# Missions that still occupy capacity at their centre, and those a volunteer still has to work on.
LIVE_MISSION = ("assigned", "accepted", "picked_up", "delivered")
OPEN_MISSION = ("assigned", "accepted", "picked_up")


def load_kg(quantity: float, unit: str) -> float:
    return round(float(quantity) * LOAD_FACTOR[unit], 3)
