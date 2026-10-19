"""FR-016: two concurrent reservations of the same offer, exactly one wins."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from secondchance.identity import Claims
from secondchance.db import tenant_transaction
from secondchance.offers import reserve_offer
from secondchance.seed import TENANT_IT


def test_concurrent_reservations_only_one_wins(available_offer: uuid.UUID) -> None:
    both_read = threading.Barrier(2)

    def attempt(n: int) -> int | None:
        actor = Claims(sub=f"coordinator-{n}", tenant_id=TENANT_IT, role="coordinator")
        with tenant_transaction(TENANT_IT, "coordinator") as session:
            seen = session.execute(
                text("SELECT version FROM donation_offer WHERE id = :id"), {"id": available_offer}
            ).scalar_one()
            both_read.wait(timeout=10)  # both hold version 1 before either writes
            return reserve_offer(session, available_offer, seen, actor, f"concurrency-{n}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))

    assert set(results) == {2, None}
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        status, version = session.execute(
            text("SELECT status, version FROM donation_offer WHERE id = :id"), {"id": available_offer}
        ).one()
        audits = session.execute(
            text("SELECT count(*) FROM audit_event WHERE object_id = :id"), {"id": available_offer}
        ).scalar_one()
    assert (status, version, audits) == ("reserved", 2, 1)


def test_stale_version_loses_even_while_still_available(available_offer: uuid.UUID) -> None:
    actor = Claims(sub="coordinator", tenant_id=TENANT_IT, role="coordinator")
    with tenant_transaction(TENANT_IT, "donor") as session:  # donor edits the offer meanwhile
        session.execute(
            text("UPDATE donation_offer SET quantity = 4, version = version + 1 WHERE id = :id"),
            {"id": available_offer},
        )
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        assert reserve_offer(session, available_offer, 1, actor, "stale") is None
        assert reserve_offer(session, available_offer, 2, actor, "fresh") == 3
