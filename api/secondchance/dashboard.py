"""Operational dashboard (FR-052, FR-053): aggregates only, computed from domain tables under RLS.

No person is identifiable from the result: no subjects, no names, no per-volunteer figures. The
same load factors as the solver turn quantities into kg (secondchance.logistics). Every figure is
scoped to the caller's network by RLS and to the chosen window on the record's creation time.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

def _rate(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summary(session: Session, days: int) -> dict:
    window = {"days": days}
    offers = {
        row.status: {"count": row.count, "kg": float(row.kg)}
        for row in session.execute(
            text(
                "SELECT status, count(*) AS count, coalesce(sum(quantity * CASE unit WHEN 'pcs' THEN 0.5 ELSE 1 END), 0) AS kg"
                " FROM donation_offer WHERE created_at > now() - make_interval(days => :days) GROUP BY status"
            ),
            window,
        )
    }
    missions = {
        row.status: row.count
        for row in session.execute(
            text("SELECT status, count(*) AS count FROM mission WHERE created_at > now() - make_interval(days => :days)"
                 " GROUP BY status"),
            window,
        )
    }
    impact = session.execute(
        text(
            "SELECT coalesce(sum(received_quantity * CASE unit WHEN 'pcs' THEN 0.5 ELSE 1 END)"
            "   FILTER (WHERE receipt IS NOT NULL), 0) AS kg_received,"
            " count(*) FILTER (WHERE receipt = 'confirmed') AS confirmed,"
            " count(*) FILTER (WHERE receipt = 'exception') AS exceptions,"
            " count(*) FILTER (WHERE status = 'delivered' AND delivered_at <= deliver_before) AS on_time,"
            " count(*) FILTER (WHERE status = 'delivered') AS delivered,"
            " count(*) FILTER (WHERE status = 'failed') AS failed,"
            " count(*) FILTER (WHERE status IN ('delivered', 'failed')) AS finished,"
            " sum(reassignments) AS reassignments"
            " FROM mission WHERE created_at > now() - make_interval(days => :days)"
        ),
        window,
    ).one()
    allocation = session.execute(
        text(
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM m.created_at - o.created_at) / 3600)"
            " AS median_hours FROM mission m JOIN donation_offer o ON o.id = m.offer_id"
            " WHERE m.created_at > now() - make_interval(days => :days)"
        ),
        window,
    ).scalar_one_or_none()
    proposals = {
        row.status: row.count
        for row in session.execute(
            text("SELECT status, count(*) AS count FROM allocation_proposal"
                 " WHERE created_at > now() - make_interval(days => :days) GROUP BY status"),
            window,
        )
    }
    last_run = session.execute(
        text("SELECT id, status, created_at, finished_at, stats->'proposals' AS proposals,"
             " jsonb_array_length(coalesce(stats->'unassigned', '[]'::jsonb)) AS unassigned"
             " FROM matching_run ORDER BY created_at DESC, id LIMIT 1")
    ).mappings().one_or_none()
    runs = session.execute(
        text("SELECT count(*) FROM matching_run WHERE created_at > now() - make_interval(days => :days)"), window
    ).scalar_one()
    centres = [
        {**dict(row), "capacity_kg": float(row["capacity_kg"]), "committed_today_kg": float(row["committed_today_kg"]),
         "utilisation": _rate(float(row["committed_today_kg"]), float(row["capacity_kg"]))}
        for row in session.execute(
            text(
                "SELECT c.id, c.name, c.status, c.daily_capacity_kg AS capacity_kg,"
                " coalesce((SELECT sum(m.quantity * CASE m.unit WHEN 'pcs' THEN 0.5 ELSE 1 END) FROM mission m"
                "   WHERE m.center_id = c.id AND m.status IN ('assigned', 'accepted', 'picked_up', 'delivered')"
                "   AND (m.deliver_after AT TIME ZONE c.timezone)::date = (now() AT TIME ZONE c.timezone)::date), 0)"
                "   AS committed_today_kg"
                " FROM center c ORDER BY c.name, c.id"
            )
        ).mappings()
    ]
    categories = [
        {"category": row.category, "kg_offered": float(row.kg_offered), "kg_received": float(row.kg_received)}
        for row in session.execute(
            text(
                "SELECT o.category, sum(o.quantity * CASE o.unit WHEN 'pcs' THEN 0.5 ELSE 1 END) AS kg_offered,"
                " coalesce(sum(m.received_quantity * CASE m.unit WHEN 'pcs' THEN 0.5 ELSE 1 END)"
                "   FILTER (WHERE m.receipt IS NOT NULL), 0) AS kg_received"
                " FROM donation_offer o LEFT JOIN mission m ON m.offer_id = o.id AND m.status <> 'cancelled'"
                " WHERE o.created_at > now() - make_interval(days => :days) GROUP BY o.category ORDER BY kg_offered DESC"
            ),
            window,
        )
    ]
    email_pending = session.execute(
        text("SELECT count(*) FROM notification_delivery WHERE status = 'pending'")
    ).scalar_one()
    decided = proposals.get("approved", 0) + proposals.get("rejected", 0)
    return {
        "window_days": days,
        "offers": {
            "by_status": offers,
            "published": sum(item["count"] for item in offers.values()),
            "kg_published": round(sum(item["kg"] for item in offers.values()), 3),
            "expired": offers.get("expired", {}).get("count", 0),
        },
        "missions": {
            "by_status": missions,
            "open": sum(missions.get(s, 0) for s in ("assigned", "accepted", "picked_up")),
            "failure_rate": _rate(impact.failed, impact.finished),
            "on_time_rate": _rate(impact.on_time, impact.delivered),
            "reassignments": int(impact.reassignments or 0),
            "median_allocation_hours": round(float(allocation), 2) if allocation is not None else None,
        },
        "impact": {
            "kg_received": round(float(impact.kg_received), 3),
            "receipts_confirmed": impact.confirmed,
            "receipt_exceptions": impact.exceptions,
        },
        "matching": {
            "runs": runs,
            "proposals": proposals,
            "open_proposals": proposals.get("proposed", 0),
            "approval_rate": _rate(proposals.get("approved", 0), decided),
            "last_run": dict(last_run) if last_run else None,
        },
        "centres": centres,
        "categories": categories,
        "notifications": {"email_pending": email_pending},
    }
