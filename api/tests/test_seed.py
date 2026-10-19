from sqlalchemy import text

from secondchance.db import tenant_transaction
from secondchance.seed import DEMO_USERS, TENANT_DK, TENANT_IT, _id, seed


def test_seed_is_idempotent() -> None:
    seed()  # second run: the session fixture already seeded once
    for key, tenant in (("it", TENANT_IT), ("dk", TENANT_DK)):
        with tenant_transaction(tenant, "coordinator") as session:
            orgs = session.execute(
                text("SELECT count(*) FROM organization WHERE id IN (:ngo, :donor)"),
                {"ngo": _id(f"{key}/org/ngo"), "donor": _id(f"{key}/org/donor")},
            ).scalar_one()
            members = session.execute(
                text("SELECT count(*) FROM membership WHERE subject LIKE 'demo-%' AND status = 'active'")
            ).scalar_one()
        assert orgs == 2
        assert members == sum(1 for u in DEMO_USERS if u["tenant"] == tenant)
