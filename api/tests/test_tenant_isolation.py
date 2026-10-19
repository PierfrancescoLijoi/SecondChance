"""FR-002 / NFR-003: tenant A never sees or touches tenant B, even without a WHERE."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from secondchance import db
from secondchance.db import SessionLocal, tenant_transaction
from secondchance.seed import TENANT_DK, TENANT_IT, _id

TABLES = ("tenant", "organization", "center", "donation_offer")


def test_every_table_with_tenant_id_has_rls() -> None:
    # Guards future migrations: a new tenant table without RLS fails here.
    with SessionLocal() as session:
        unprotected = session.execute(
            text(
                "SELECT c.relname FROM pg_class c"
                " JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'"
                " JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'"
                " WHERE c.relkind = 'r' AND NOT (c.relrowsecurity AND EXISTS ("
                "   SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid))"
            )
        ).scalars().all()
    assert unprotected == []


def test_tenant_setting_does_not_survive_on_pooled_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    single = create_engine(os.environ["SECONDCHANCE_DATABASE_URL"], pool_size=1, max_overflow=0)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(single))
    try:
        with db.tenant_transaction(TENANT_IT, "coordinator") as session:
            pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
        with db.SessionLocal() as session:  # same physical connection, no tenant set
            assert session.execute(text("SELECT pg_backend_pid()")).scalar_one() == pid
            assert session.execute(text("SELECT count(*) FROM donation_offer")).scalar_one() == 0
    finally:
        single.dispose()


def test_app_role_is_not_owner_and_cannot_bypass_rls() -> None:
    with SessionLocal() as session:
        role = session.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        owned = session.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
                 " AND tableowner = current_user")
        ).scalar_one()
    assert tuple(role) == (False, False)
    assert owned == 0


@pytest.mark.parametrize("table", TABLES)
def test_query_without_where_returns_only_own_tenant(table: str) -> None:
    column = "id" if table == "tenant" else "tenant_id"
    for tenant in (TENANT_IT, TENANT_DK):
        with tenant_transaction(tenant, "coordinator") as session:
            seen = set(session.execute(text(f"SELECT {column} FROM {table}")).scalars())
        assert seen == {tenant}


@pytest.mark.parametrize("table", TABLES)
def test_without_tenant_setting_nothing_is_visible(table: str) -> None:
    with SessionLocal() as session:
        assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_filtering_on_other_tenant_id_returns_nothing() -> None:
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        count = session.execute(
            text("SELECT count(*) FROM donation_offer WHERE tenant_id = :t"), {"t": TENANT_DK}
        ).scalar_one()
    assert count == 0


def test_update_cannot_reach_other_tenant_rows() -> None:
    dk_offer = _id("dk/offer/pasta")
    with tenant_transaction(TENANT_IT, "coordinator") as session:
        result = session.execute(
            text("UPDATE donation_offer SET status = 'cancelled' WHERE id = :id"), {"id": dk_offer}
        )
    with tenant_transaction(TENANT_DK, "coordinator") as session:
        status = session.execute(
            text("SELECT status FROM donation_offer WHERE id = :id"), {"id": dk_offer}
        ).scalar_one()
    assert result.rowcount == 0
    assert status == "available"


def test_insert_for_other_tenant_is_rejected() -> None:
    with pytest.raises(ProgrammingError, match="row-level security"):
        with tenant_transaction(TENANT_IT, "org_admin") as session:
            session.execute(
                text("INSERT INTO organization (tenant_id, name, kind) VALUES (:t, 'intruder', 'ngo')"),
                {"t": TENANT_DK},
            )


def test_reference_to_other_tenant_organization_is_rejected() -> None:
    with pytest.raises(IntegrityError):
        with tenant_transaction(TENANT_IT, "org_admin") as session:
            session.execute(
                text("INSERT INTO center (organization_id, name) VALUES (:org, 'leak')"),
                {"org": _id("dk/org/ngo")},
            )


def test_app_role_hardening_is_in_place() -> None:
    with SessionLocal() as session:
        can_temp = session.execute(text("SELECT has_database_privilege(current_user, current_database(), 'TEMP')")).scalar_one()
        can_create = session.execute(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")).scalar_one()
        timeouts = {
            name: session.execute(text(f"SELECT current_setting('{name}')")).scalar_one()
            for name in ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout")
        }
    assert (can_temp, can_create) == (False, False)
    assert "0" not in timeouts.values()


def test_no_security_definer_functions_or_permissive_policies() -> None:
    with SessionLocal() as session:
        definers = session.execute(
            text("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                 " WHERE n.nspname = 'public' AND p.prosecdef")
        ).scalars().all()
        trivial = session.execute(
            # The only unconditional policies are the maintenance role's (migration 0005).
            text("SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public'"
                 " AND (qual = 'true' OR with_check = 'true') AND roles <> '{secondchance_maintenance}'")
        ).all()
    assert definers == []
    assert trivial == []


def test_no_role_bypasses_row_level_security() -> None:
    with SessionLocal() as session:
        bypass = session.execute(
            text("SELECT rolname FROM pg_roles WHERE rolbypassrls AND rolname LIKE 'secondchance%'")
        ).scalars().all()
    assert bypass == []
