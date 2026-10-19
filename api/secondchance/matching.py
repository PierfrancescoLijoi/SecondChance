"""Allocation matching (FR-020, FR-021): deterministic rules first, then OR-Tools CP-SAT.

1. Rules decide which (offer, centre, day) options exist and record why every other pairing is
   impossible: accepted category, storage, an acceptance slot inside the delivery window, the
   use_by / best_before rule of the network's country (FR-012, FR-017) and the remaining daily
   capacity of the centre (FR-014).
2. CP-SAT chooses at most one option per offer, keeps every centre within its remaining daily
   capacity and maximises allocated offers first, then quantity, urgency, proximity, promptness.
3. The result is a set of pending proposals bound to a content hash. Nothing is reserved until an
   authorised person approves one (FR-022, secondchance.missions.decide_proposal).

Fixed input + fixed seed + one search worker + a deterministic time budget = the same answer on
every run; the input checksum is stored with the run so a result can be reproduced.
"""

import hashlib
import json
import logging
import math
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance import audit
from secondchance.db import tenant_transaction
from secondchance.logistics import load_kg
from secondchance.notifications import network_language, notify
from secondchance.observability import meter

log = logging.getLogger(__name__)

SOLVER_ROLE = "solver"
SOLVER_ACTOR = "secondchance-solver"
LEASE = timedelta(minutes=5)  # above the solver's time limit, below the jobs queue visibility timeout
MAX_ATTEMPTS = 5
MAX_OFFERS = 500
MIN_OVERLAP = timedelta(minutes=30)
TRANSIT = {"ambient": timedelta(hours=24), "chilled": timedelta(hours=4), "frozen": timedelta(hours=4)}
ROAD_FACTOR = 1.3  # straight line to road distance (PRD 5.3); a travel-time matrix replaces it with FR-024
UNKNOWN_DISTANCE_KM = 25.0  # a centre without coordinates never beats a known nearby one
MAX_ALTERNATIVES = 3

runs_counter = meter.create_counter("secondchance.matching.runs", description="Matching runs by outcome")
solve_ms = meter.create_histogram("secondchance.matching.solve_ms", unit="ms", description="CP-SAT wall time")


@dataclass(frozen=True)
class OfferIn:
    id: str
    version: int
    category: str
    quantity: float
    unit: str
    date_kind: str
    expires_on: date
    storage: str
    pickup_from: datetime
    pickup_until: datetime
    latitude: float | None = None
    longitude: float | None = None

    @property
    def load_kg(self) -> float:
        return load_kg(self.quantity, self.unit)


@dataclass(frozen=True)
class CenterIn:
    id: str
    name: str
    accepted_categories: tuple[str, ...]
    storage_capabilities: tuple[str, ...]
    capacity_kg: float
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class SlotIn:
    center_id: str
    local_date: date
    opens_at: datetime
    closes_at: datetime


@dataclass(frozen=True)
class Problem:
    now: datetime
    country: str
    rule_version: int | None
    grace_days: int
    offers: tuple[OfferIn, ...]
    centers: tuple[CenterIn, ...]
    slots: tuple[SlotIn, ...]
    committed_kg: dict[tuple[str, str], float] = field(default_factory=dict)
    time_limit_ms: int = 5000
    seed: int = 0

    def checksum(self) -> str:
        payload = asdict(self) | {"committed_kg": sorted([*key, kg] for key, kg in self.committed_kg.items())}
        return hashlib.sha256(_canonical(payload).encode()).hexdigest()


@dataclass(frozen=True)
class Option:
    offer_id: str
    center_id: str
    local_date: date
    deliver_after: datetime
    deliver_before: datetime
    distance_km: float | None
    score: int
    terms: dict[str, int]
    expiry_limit: date


@dataclass(frozen=True)
class Assignment:
    offer: OfferIn
    option: Option
    explanation: dict
    alternatives: list[dict]


@dataclass(frozen=True)
class Solution:
    status: str  # OPTIMAL, FEASIBLE or the CP-SAT status that produced no usable answer
    objective: int
    assignments: tuple[Assignment, ...]
    unassigned: tuple[dict, ...]
    input_sha256: str
    wall_ms: int


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not serialisable: {type(value)!r}")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def distance_km(a: tuple[float | None, float | None], b: tuple[float | None, float | None]) -> float | None:
    """Great-circle distance times the road factor; None when a coordinate is missing."""
    if None in (*a, *b):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(2 * 6371.0 * math.asin(math.sqrt(h)) * ROAD_FACTOR, 2)


def _expiry_limit(offer: OfferIn, grace_days: int) -> date:
    """FR-012: never after use_by; best_before only within the country's grace (FR-017)."""
    return offer.expires_on if offer.date_kind == "use_by" else offer.expires_on + timedelta(days=grace_days)


def _score(offer: OfferIn, deliver_after: datetime, window_start: datetime, km: float | None, limit: date,
           local_date: date) -> tuple[int, dict[str, int]]:
    days_left = (limit - local_date).days
    if offer.date_kind == "use_by":
        urgency = 3000 if days_left <= 1 else 1500 if days_left <= 3 else 500 if days_left <= 7 else 0
    else:
        urgency = 500 if days_left <= 7 else 0
    terms = {
        "base": 10_000,  # every allocated offer first: food reaching a centre beats any optimisation
        "quantity": min(round(offer.load_kg * 10), 5000),
        "urgency": urgency,
        "distance": -min(round((km if km is not None else UNKNOWN_DISTANCE_KM) * 20), 5000),
        "delay": -min(round((deliver_after - window_start).total_seconds() / 360), 2000),
    }
    return sum(terms.values()), terms


def options_for(problem: Problem) -> tuple[list[Option], dict[str, set[str]]]:
    """Every allowed (offer, centre, day) option, and the reasons for every rejected offer-centre pairing."""
    slots_by_center: dict[str, list[SlotIn]] = defaultdict(list)
    for slot in sorted(problem.slots, key=lambda s: (s.center_id, s.opens_at)):
        slots_by_center[slot.center_id].append(slot)
    options: list[Option] = []
    reasons: dict[str, set[str]] = defaultdict(set)
    for offer in sorted(problem.offers, key=lambda o: o.id):
        window_start = max(offer.pickup_from, problem.now)
        window_end = offer.pickup_until + TRANSIT[offer.storage]
        limit = _expiry_limit(offer, problem.grace_days)
        if window_end - window_start < MIN_OVERLAP:
            reasons[offer.id].add("pickup_window_passed")
            continue
        if not problem.centers:
            reasons[offer.id].add("no_active_centre")
            continue
        for center in sorted(problem.centers, key=lambda c: c.id):
            static = []
            if offer.category not in center.accepted_categories:
                static.append("category_not_accepted")
            if offer.storage not in center.storage_capabilities:
                static.append("storage_unavailable")
            if offer.load_kg > center.capacity_kg:
                static.append("exceeds_daily_capacity")
            if static:
                reasons[offer.id].update(static)
                continue
            seen_days: set[date] = set()
            slot_failures: set[str] = set()
            km = distance_km((offer.latitude, offer.longitude), (center.latitude, center.longitude))
            for slot in slots_by_center.get(center.id, []):
                start, end = max(slot.opens_at, window_start), min(slot.closes_at, window_end)
                if end - start < MIN_OVERLAP or slot.local_date in seen_days:
                    continue
                if slot.local_date > limit:
                    slot_failures.add("past_use_by" if offer.date_kind == "use_by" else "past_best_before_grace")
                    continue
                remaining = center.capacity_kg - problem.committed_kg.get((center.id, slot.local_date.isoformat()), 0.0)
                if offer.load_kg > remaining:
                    slot_failures.add("capacity_full")
                    continue
                seen_days.add(slot.local_date)
                score, terms = _score(offer, start, window_start, km, limit, slot.local_date)
                options.append(Option(offer.id, center.id, slot.local_date, start, end, km, score, terms, limit))
            if not seen_days:
                reasons[offer.id].update(slot_failures or {"no_acceptance_slot"})
    return options, reasons


def solve(problem: Problem) -> Solution:
    from ortools.sat.python import cp_model

    started = time.monotonic()
    options, reasons = options_for(problem)
    offers = {offer.id: offer for offer in problem.offers}
    centers = {center.id: center for center in problem.centers}
    model = cp_model.CpModel()
    chosen = [model.new_bool_var(f"x{i}") for i in range(len(options))]
    by_offer: dict[str, list[int]] = defaultdict(list)
    by_day: dict[tuple[str, date], list[int]] = defaultdict(list)
    for i, option in enumerate(options):
        by_offer[option.offer_id].append(i)
        by_day[(option.center_id, option.local_date)].append(i)
    for indices in by_offer.values():
        model.add_at_most_one(chosen[i] for i in indices)
    for (center_id, day), indices in by_day.items():
        remaining = centers[center_id].capacity_kg - problem.committed_kg.get((center_id, day.isoformat()), 0.0)
        model.add(sum(round(offers[options[i].offer_id].load_kg * 1000) * chosen[i] for i in indices)
                  <= math.floor(remaining * 1000))
    model.maximize(sum((option.score * chosen[i] for i, option in enumerate(options)), cp_model.LinearExpr.constant(0)))

    solver = cp_model.CpSolver()
    # Reproducible (FR-021): one worker, fixed seed, a deterministic budget; wall time is only a safety net.
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = problem.seed
    solver.parameters.max_deterministic_time = problem.time_limit_ms / 1000
    # 1.5x keeps a full jobs batch (5 records, 30 s limit each) inside the 300 s Lambda timeout.
    solver.parameters.max_time_in_seconds = problem.time_limit_ms / 1000 * 1.5
    status = solver.status_name(solver.solve(model))
    wall_ms = int((time.monotonic() - started) * 1000)
    solve_ms.record(wall_ms)
    if status not in ("OPTIMAL", "FEASIBLE"):
        return Solution(status, 0, (), (), problem.checksum(), wall_ms)

    picked = {options[i].offer_id: options[i] for i in range(len(options)) if solver.boolean_value(chosen[i])}
    assignments = []
    for offer_id in sorted(picked):
        option, offer = picked[offer_id], offers[offer_id]
        center = centers[option.center_id]
        committed = problem.committed_kg.get((center.id, option.local_date.isoformat()), 0.0)
        explanation = {
            "satisfied": [
                {"code": "category_accepted", "value": offer.category},
                {"code": "storage", "value": offer.storage},
                {"code": "slot", "from": _iso(option.deliver_after), "until": _iso(option.deliver_before)},
                {"code": "expiry", "kind": offer.date_kind, "limit": option.expiry_limit.isoformat()},
                {"code": "capacity", "load_kg": round(offer.load_kg, 3), "remaining_kg": round(center.capacity_kg - committed, 3),
                 "capacity_kg": round(center.capacity_kg, 3)},
                {"code": "distance", "km": option.distance_km},
            ],
            "objective": option.terms,
            "rule": {"country": problem.country, "version": problem.rule_version, "grace_days": problem.grace_days},
        }
        others: dict[str, Option] = {}
        for i in by_offer[offer_id]:
            candidate = options[i]
            if candidate.center_id != option.center_id and (
                candidate.center_id not in others or candidate.score > others[candidate.center_id].score
            ):
                others[candidate.center_id] = candidate
        alternatives = [
            {"center_id": alt.center_id, "center_name": centers[alt.center_id].name, "deliver_after": _iso(alt.deliver_after),
             "deliver_before": _iso(alt.deliver_before), "distance_km": alt.distance_km, "score": alt.score}
            for alt in sorted(others.values(), key=lambda a: (-a.score, a.center_id))[:MAX_ALTERNATIVES]
        ]
        assignments.append(Assignment(offer, option, explanation, alternatives))
    unassigned = tuple(
        {"offer_id": offer.id, "category": offer.category, "quantity": offer.quantity, "unit": offer.unit,
         "reasons": sorted(reasons.get(offer.id) or {"capacity_used_by_higher_priority"})}
        for offer in sorted(problem.offers, key=lambda o: o.id) if offer.id not in picked
    )
    return Solution(status, round(solver.objective_value), tuple(assignments), unassigned, problem.checksum(), wall_ms)


# --- proposals bound to their content (FR-022) ---

def proposal_content(*, offer_id, offer_version, center_id, quantity, unit, load_kg, deliver_after, deliver_before,
                     explanation, alternatives) -> dict:
    """What an approver confirms. Normalised so the same proposal hashes the same from memory or the database."""
    return {
        "offer_id": str(offer_id), "offer_version": int(offer_version), "center_id": str(center_id),
        "quantity": f"{float(quantity):.3f}", "unit": unit, "load_kg": f"{float(load_kg):.3f}",
        "deliver_after": _iso(deliver_after), "deliver_before": _iso(deliver_before),
        "explanation": explanation, "alternatives": alternatives,
    }


def content_sha256(content: dict) -> str:
    return hashlib.sha256(_canonical(content).encode()).hexdigest()


def row_sha256(row) -> str:
    return content_sha256(proposal_content(**{key: row[key] for key in (
        "offer_id", "offer_version", "center_id", "quantity", "unit", "load_kg", "deliver_after", "deliver_before",
        "explanation", "alternatives")}))


# --- database side: load, claim, complete ---

def load_problem(session: Session, time_limit_ms: int, seed: int) -> Problem:
    now = session.execute(text("SELECT now()")).scalar_one()
    country = session.execute(text("SELECT country FROM tenant WHERE id = current_tenant_id()")).scalar_one()
    rule = session.execute(
        text("SELECT version, best_before_grace_days FROM food_rule WHERE country = :country AND valid_from <= current_date"
             " ORDER BY version DESC LIMIT 1"),
        {"country": country},
    ).one_or_none()
    offers = tuple(
        OfferIn(str(r.id), r.version, r.category, float(r.quantity), r.unit, r.date_kind, r.expires_on, r.storage,
                r.pickup_from, r.pickup_until, r.latitude, r.longitude)
        for r in session.execute(
            text(
                "SELECT o.id, o.version, o.category, o.quantity, o.unit, o.date_kind, o.expires_on, o.storage,"
                " o.pickup_from, o.pickup_until, ST_Y(g.location::geometry) AS latitude, ST_X(g.location::geometry) AS longitude"
                " FROM donation_offer o JOIN organization g ON g.id = o.donor_id"
                " WHERE o.status = 'available' AND o.pickup_until > now() ORDER BY o.id LIMIT :limit"
            ),
            {"limit": MAX_OFFERS},
        )
    )
    centers = tuple(
        CenterIn(str(r.id), r.name, tuple(r.accepted_categories), tuple(r.storage_capabilities), float(r.daily_capacity_kg),
                 r.latitude, r.longitude)
        for r in session.execute(
            text(
                "SELECT id, name, accepted_categories, storage_capabilities, daily_capacity_kg,"
                " ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude"
                " FROM center WHERE status = 'active' ORDER BY id"
            )
        )
    )
    horizon = max([2] + [(o.pickup_until - now).days + 2 for o in offers])
    slots = tuple(
        SlotIn(str(r.center_id), r.local_date, r.opens_at, r.closes_at)
        for r in session.execute(
            text(
                "SELECT s.center_id, d.day AS local_date,"
                " (d.day + s.opens) AT TIME ZONE c.timezone AS opens_at,"
                " (d.day + s.closes) AT TIME ZONE c.timezone AS closes_at"
                " FROM center c JOIN center_slot s ON s.center_id = c.id"
                " CROSS JOIN LATERAL (SELECT g::date AS day FROM generate_series("
                "   (now() AT TIME ZONE c.timezone)::date, (now() AT TIME ZONE c.timezone)::date + CAST(:horizon AS integer),"
                "   interval '1 day') AS g) d"
                " WHERE c.status = 'active' AND extract(isodow FROM d.day) = s.weekday"
                " ORDER BY s.center_id, opens_at"
            ),
            {"horizon": min(horizon, 31)},
        )
    )
    committed = {
        (str(r.center_id), r.day.isoformat()): float(r.kg)
        for r in session.execute(
            text(
                "SELECT m.center_id, (m.deliver_after AT TIME ZONE c.timezone)::date AS day,"
                " sum(m.quantity * CASE m.unit WHEN 'pcs' THEN 0.5 ELSE 1 END) AS kg"
                " FROM mission m JOIN center c ON c.id = m.center_id"
                " WHERE m.status IN ('assigned', 'accepted', 'picked_up', 'delivered') GROUP BY 1, 2"
            )
        )
    }
    return Problem(
        now=now, country=country, rule_version=rule.version if rule else None,
        grace_days=rule.best_before_grace_days if rule else 0,  # no rule: conservative, nothing past best before
        offers=offers, centers=centers, slots=slots, committed_kg=committed, time_limit_ms=time_limit_ms, seed=seed,
    )


def start_run(session: Session, claims, time_limit_ms: int, correlation_id: str) -> tuple[uuid.UUID, dict]:
    """Creates the run; send the returned message after the commit (the requeue job covers a lost send)."""
    run_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO matching_run (id, requested_by, requested_role, time_limit_ms, correlation_id)"
            " VALUES (:id, :sub, :role, :limit, :cid)"
        ),
        {"id": run_id, "sub": claims.sub, "role": claims.role, "limit": time_limit_ms, "cid": correlation_id},
    )
    audit.record(session, claims.sub, claims.role, "matching.start", "matching_run", run_id, correlation_id,
                 {"time_limit_ms": time_limit_ms})
    return run_id, job_message(claims.tenant_id, run_id, correlation_id)


def job_message(tenant_id, run_id, correlation_id: str) -> dict:
    return {"type": "match", "tenant_id": str(tenant_id), "run_id": str(run_id), "correlation_id": correlation_id}


def _claim(tenant_id: uuid.UUID, run_id: uuid.UUID):
    with tenant_transaction(tenant_id, SOLVER_ROLE) as session:
        session.execute(
            text(
                "UPDATE matching_run SET status = 'failed', error_category = 'attempts_exhausted', finished_at = now(),"
                " lease_until = NULL WHERE id = :id AND status = 'running' AND lease_until < now() AND attempt >= :max"
            ),
            {"id": run_id, "max": MAX_ATTEMPTS},
        )
        return session.execute(
            text(
                "UPDATE matching_run SET status = 'running', attempt = attempt + 1, lease_until = now() + :lease,"
                " started_at = coalesce(started_at, now())"
                " WHERE id = :id AND (status = 'queued' OR (status = 'running' AND lease_until < now()))"
                " RETURNING attempt, time_limit_ms, random_seed, requested_by, correlation_id"
            ),
            {"id": run_id, "lease": LEASE},
        ).mappings().one_or_none()


def process(tenant_id: uuid.UUID, run_id: uuid.UUID) -> str:
    """Runs one matching job from the queue. Returns what happened, for logs and tests."""
    claim = _claim(tenant_id, run_id)
    if claim is None:
        return "not_claimable"  # finished already, leased by a live worker, or another tenant's id
    with tenant_transaction(tenant_id, SOLVER_ROLE) as session:
        problem = load_problem(session, claim["time_limit_ms"], claim["random_seed"])
    try:
        solution = solve(problem)  # no transaction held while the solver works
    except Exception:  # noqa: BLE001 - a solver failure is recorded on the run, never retried forever
        log.exception("matching run %s: solver failed", run_id)
        solution = None
    return _complete(tenant_id, run_id, claim, problem, solution)


def _complete(tenant_id: uuid.UUID, run_id: uuid.UUID, claim, problem: Problem, solution: Solution | None) -> str:
    if solution is None or solution.status not in ("OPTIMAL", "FEASIBLE"):
        status, error = "failed", "solver_error" if solution is None else f"solver_{solution.status.lower()}"
    elif solution.assignments or not problem.offers:
        status, error = "succeeded", None
    else:
        status, error = "infeasible", None
    stats = {
        "offers": len(problem.offers), "centres": len(problem.centers),
        "proposals": len(solution.assignments) if solution else 0,
        "unassigned": list(solution.unassigned) if solution else [],
        "wall_ms": solution.wall_ms if solution else None,
    }
    with tenant_transaction(tenant_id, SOLVER_ROLE) as session:
        fenced = session.execute(
            text(
                "UPDATE matching_run SET status = :status, error_category = :error, input_sha256 = :checksum,"
                " objective = :objective, solver_status = :solver_status, stats = CAST(:stats AS jsonb),"
                " finished_at = now(), lease_until = NULL"
                " WHERE id = :id AND attempt = :attempt AND status = 'running'"
            ),
            {
                "status": status, "error": error, "checksum": problem.checksum(),
                "objective": solution.objective if solution else None,
                "solver_status": solution.status if solution else None,
                "stats": _canonical(stats), "id": run_id, "attempt": claim["attempt"],
            },
        ).rowcount
        if fenced == 0:
            session.rollback()
            return "fenced"  # the lease expired and another worker owns the run now
        if status != "failed":
            # This run reconsidered every available offer: older open proposals are out of date.
            session.execute(
                text("UPDATE allocation_proposal SET status = 'superseded' WHERE status = 'proposed' AND run_id <> :run"),
                {"run": run_id},
            )
            for item in solution.assignments:
                _insert_proposal(session, run_id, item)
        notify(session, recipient=claim["requested_by"], kind="proposals_ready" if status == "succeeded" else f"matching_{status}",
               object_type="matching_run", object_id=run_id, language=network_language(session))
        audit.record(session, SOLVER_ACTOR, SOLVER_ROLE, "matching.complete", "matching_run", run_id,
                     claim["correlation_id"], {"status": status, "proposals": stats["proposals"]},
                     outcome="failed" if status == "failed" else "success")
    runs_counter.add(1, {"outcome": status})
    return status


def _insert_proposal(session: Session, run_id: uuid.UUID, item: Assignment) -> None:
    offer, option = item.offer, item.option
    content = proposal_content(
        offer_id=offer.id, offer_version=offer.version, center_id=option.center_id, quantity=offer.quantity,
        unit=offer.unit, load_kg=offer.load_kg, deliver_after=option.deliver_after, deliver_before=option.deliver_before,
        explanation=item.explanation, alternatives=item.alternatives,
    )
    session.execute(
        text(
            "INSERT INTO allocation_proposal (run_id, offer_id, offer_version, center_id, quantity, unit, load_kg, score,"
            " distance_km, deliver_after, deliver_before, explanation, alternatives, content_sha256)"
            " VALUES (:run, :offer, :version, :center, :quantity, :unit, :load, :score, :km, :after, :before,"
            " CAST(:explanation AS jsonb), CAST(:alternatives AS jsonb), :sha)"
        ),
        {
            "run": run_id, "offer": offer.id, "version": offer.version, "center": option.center_id,
            "quantity": offer.quantity, "unit": offer.unit, "load": offer.load_kg, "score": option.score,
            "km": option.distance_km, "after": option.deliver_after, "before": option.deliver_before,
            "explanation": json.dumps(item.explanation), "alternatives": json.dumps(item.alternatives),
            "sha": content_sha256(content),
        },
    )


def requeue_stale(connection, queue) -> int:
    """Runs whose message was lost or whose worker died (as secondchance_maintenance)."""
    rows = connection.execute(
        text(
            "SELECT tenant_id, id, correlation_id FROM matching_run"
            " WHERE (status = 'queued' AND created_at < now() - interval '2 minutes')"
            " OR (status = 'running' AND lease_until < now())"
        )
    ).all()
    for tenant_id, run_id, correlation_id in rows:
        queue.send(job_message(tenant_id, run_id, correlation_id))
    return len(rows)


def self_check() -> str:
    """Deployment probe: the native OR-Tools library loads and solves inside the Lambda sandbox."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    a, b = model.new_bool_var("a"), model.new_bool_var("b")
    model.add(a + b <= 1)
    model.maximize(2 * a + b)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.max_time_in_seconds = 5
    if solver.status_name(solver.solve(model)) != "OPTIMAL" or not solver.boolean_value(a):
        raise RuntimeError("OR-Tools CP-SAT self-check failed")
    return "ok"
