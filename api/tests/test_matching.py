"""FR-020/FR-021: deterministic rules, OR-Tools CP-SAT, reproducible results and readable explanations.

Pure solver tests: no database, a fixed reference time, so every expectation is exact.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from secondchance.logistics import LOAD_FACTOR, load_kg
from secondchance.matching import (
    CenterIn,
    OfferIn,
    Problem,
    SlotIn,
    content_sha256,
    distance_km,
    proposal_content,
    self_check,
    solve,
)

NOW = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)  # a Monday
TODAY = NOW.date()
CATS = ("dairy", "dry_goods", "bakery", "frozen", "fruit_vegetables")


def offer(key: str, category: str = "dairy", quantity: float = 10, storage: str = "chilled", date_kind: str = "use_by",
          expires_in: int = 2, start_in: int = 1, hours: int = 3, unit: str = "kg") -> OfferIn:
    start = NOW + timedelta(hours=start_in)
    return OfferIn(key, 1, category, quantity, unit, date_kind, TODAY + timedelta(days=expires_in), storage, start,
                   start + timedelta(hours=hours), 45.07, 7.68)


def center(key: str, storage=("ambient", "chilled"), capacity: float = 100, lat: float = 45.08, lon: float = 7.69,
           categories=CATS) -> CenterIn:
    return CenterIn(key, f"Centre {key}", tuple(categories), tuple(storage), capacity, lat, lon)


def daily_slots(center_id: str, days: int = 4, opens: time = time(0, 0), closes: time = time(23, 59)) -> list[SlotIn]:
    return [
        SlotIn(center_id, TODAY + timedelta(days=d), datetime.combine(TODAY + timedelta(days=d), opens, UTC),
               datetime.combine(TODAY + timedelta(days=d), closes, UTC))
        for d in range(days)
    ]


def problem(offers, centers, slots, committed=None, grace: int = 30) -> Problem:
    return Problem(NOW, "IT", 1, grace, tuple(offers), tuple(centers), tuple(slots), committed or {}, 2000, 0)


def assigned(solution) -> dict[str, str]:
    return {a.offer.id: a.option.center_id for a in solution.assignments}


def test_ortools_self_check_passes() -> None:
    assert self_check() == "ok"


def test_python_and_sql_load_factors_agree(owner) -> None:
    from sqlalchemy import text

    for unit, factor in LOAD_FACTOR.items():
        sql = owner.execute(text("SELECT CAST(7 * CASE CAST(:unit AS text) WHEN 'pcs' THEN 0.5 ELSE 1 END AS float8)"),
                            {"unit": unit}).scalar_one()
        assert sql == pytest.approx(7 * factor) == pytest.approx(load_kg(7, unit))


def test_same_input_gives_the_same_answer_and_checksum() -> None:
    offers = [offer(f"o{i}", quantity=10 + i) for i in range(12)]
    centers = [center("a", capacity=60), center("b", capacity=70, lat=45.10)]
    slots = daily_slots("a") + daily_slots("b")
    first, second = solve(problem(offers, centers, slots)), solve(problem(offers, centers, slots))
    assert first.status == "OPTIMAL"
    assert assigned(first) == assigned(second) and first.objective == second.objective
    assert first.input_sha256 == second.input_sha256
    assert solve(problem(offers[:-1], centers, slots)).input_sha256 != first.input_sha256


def test_capacity_per_centre_and_day_is_never_exceeded() -> None:
    offers = [offer(f"o{i}", quantity=40, expires_in=0) for i in range(4)]  # use_by today: only today's slot counts
    solution = solve(problem(offers, [center("a", capacity=100)], daily_slots("a")))
    assert len(solution.assignments) == 2  # 2 x 40 kg fit in 100 kg, a third would not
    assert sum(a.offer.load_kg for a in solution.assignments) <= 100
    assert len(solution.unassigned) == 2 and not set(assigned(solution)) & {u["offer_id"] for u in solution.unassigned}
    assert all(u["reasons"] == ["capacity_used_by_higher_priority"] for u in solution.unassigned)


def test_committed_missions_reduce_the_remaining_capacity() -> None:
    solution = solve(problem([offer("o1", quantity=30, expires_in=0)], [center("a", capacity=100)], daily_slots("a"),
                             committed={("a", TODAY.isoformat()): 80.0}))
    assert solution.assignments == ()
    assert solution.unassigned[0]["reasons"] == ["capacity_full"]


def test_hard_rules_explain_every_rejection() -> None:
    offers = [
        offer("frozen", category="frozen", storage="frozen"),
        offer("not-accepted", category="bakery", storage="ambient"),
        offer("huge", quantity=500),
        offer("expired-use-by", expires_in=-1),
        offer("best-before-too-old", category="dry_goods", storage="ambient", date_kind="best_before", expires_in=-40),
    ]
    centers = [center("a", categories=("dairy", "dry_goods", "frozen"))]
    solution = solve(problem(offers, centers, daily_slots("a")))
    reasons = {u["offer_id"]: u["reasons"] for u in solution.unassigned}
    assert solution.assignments == ()
    assert reasons == {
        "frozen": ["storage_unavailable"],
        "not-accepted": ["category_not_accepted"],
        "huge": ["exceeds_daily_capacity"],
        "expired-use-by": ["past_use_by"],
        "best-before-too-old": ["past_best_before_grace"],
    }


def test_best_before_follows_the_country_grace() -> None:
    late = offer("late", category="dry_goods", storage="ambient", date_kind="best_before", expires_in=-10)
    slots = daily_slots("a")
    assert assigned(solve(problem([late], [center("a")], slots, grace=30))) == {"late": "a"}
    assert solve(problem([late], [center("a")], slots, grace=0)).unassigned[0]["reasons"] == ["past_best_before_grace"]


def test_no_slot_in_the_delivery_window_is_a_reason() -> None:
    night_only = [SlotIn("a", TODAY, datetime.combine(TODAY, time(1, 0), UTC), datetime.combine(TODAY, time(2, 0), UTC))]
    solution = solve(problem([offer("o1", expires_in=0)], [center("a")], night_only))
    assert solution.unassigned[0]["reasons"] == ["no_acceptance_slot"]


def test_the_nearer_centre_wins_and_the_other_is_an_alternative() -> None:
    near, far = center("near", lat=45.071, lon=7.681), center("far", lat=45.30, lon=7.90)
    solution = solve(problem([offer("o1")], [far, near], daily_slots("near") + daily_slots("far")))
    [item] = solution.assignments
    assert item.option.center_id == "near"
    assert [a["center_id"] for a in item.alternatives] == ["far"]
    assert item.alternatives[0]["distance_km"] > item.option.distance_km
    codes = [s["code"] for s in item.explanation["satisfied"]]
    assert codes == ["category_accepted", "storage", "slot", "expiry", "capacity", "distance"]
    assert item.explanation["rule"] == {"country": "IT", "version": 1, "grace_days": 30}


def test_urgent_use_by_offers_win_scarce_capacity() -> None:
    urgent = offer("urgent", quantity=60, expires_in=0)
    relaxed = offer("relaxed", quantity=60, expires_in=6, date_kind="best_before", category="dry_goods", storage="ambient")
    solution = solve(problem([relaxed, urgent], [center("a", capacity=100)], daily_slots("a", days=1)))
    assert assigned(solution) == {"urgent": "a"}


def test_pieces_count_at_their_estimated_weight() -> None:
    bread = offer("bread", category="bakery", storage="ambient", quantity=150, unit="pcs", expires_in=0)
    solution = solve(problem([bread], [center("a", capacity=80)], daily_slots("a")))
    assert assigned(solution) == {"bread": "a"} and solution.assignments[0].offer.load_kg == 75


def test_an_empty_problem_is_solved_without_proposals() -> None:
    solution = solve(problem([], [center("a")], daily_slots("a")))
    assert (solution.status, solution.assignments, solution.unassigned) == ("OPTIMAL", (), ())


def test_no_centre_at_all_is_explained() -> None:
    assert solve(problem([offer("o1")], [], [])).unassigned[0]["reasons"] == ["no_active_centre"]


def test_distance_needs_both_coordinates() -> None:
    assert distance_km((None, 7.6), (45.0, 7.6)) is None
    assert distance_km((45.0, 7.6), (45.1, 7.6)) == pytest.approx(11.1 * 1.3, rel=0.01)


def test_content_hash_is_stable_across_types() -> None:
    after = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    common = dict(offer_id="o", offer_version=1, center_id="c", unit="kg", deliver_after=after,
                  deliver_before=after + timedelta(hours=1), explanation={"b": 1, "a": [1.5]}, alternatives=[])
    from decimal import Decimal

    in_memory = proposal_content(quantity=12.0, load_kg=12.0, **common)
    from_db = proposal_content(quantity=Decimal("12.000"), load_kg=Decimal("12.000"),
                               **common | {"explanation": {"a": [1.5], "b": 1}})
    assert content_sha256(in_memory) == content_sha256(from_db)
    assert content_sha256(in_memory) != content_sha256(proposal_content(quantity=11, load_kg=11, **common))


def test_dates_are_compared_on_the_slot_day() -> None:
    # use_by tomorrow, but the only open slot is the day after: never delivered past the date.
    slots = [s for s in daily_slots("a", days=3) if s.local_date == TODAY + timedelta(days=2)]
    late = offer("o1", expires_in=1, start_in=1, hours=60, storage="ambient", category="dry_goods")
    assert solve(problem([late], [center("a")], slots)).unassigned[0]["reasons"] == ["past_use_by"]
    assert date.fromisoformat(slots[0].local_date.isoformat()) > TODAY
