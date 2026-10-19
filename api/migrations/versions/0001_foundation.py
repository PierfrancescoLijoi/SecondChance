"""Foundation: tenants, organizations, centers, donation offers, audit log, RLS.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = "secondchance_app"
TENANT_TABLES = ("organization", "center", "donation_offer")


def upgrade() -> None:
    op.execute(
        """
        -- NULL when unset or reset to '' after a SET LOCAL: no tenant, no rows.
        CREATE FUNCTION current_tenant_id() RETURNS uuid
            LANGUAGE sql STABLE
            AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

        CREATE TABLE tenant (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name       text NOT NULL,
            country    char(2) NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE organization (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            name       text NOT NULL,
            kind       text NOT NULL CHECK (kind IN ('ngo', 'donor')),
            created_at timestamptz NOT NULL DEFAULT now(),
            -- Target of the composite FKs below: a row can only point inside its own tenant.
            UNIQUE (tenant_id, id)
        );

        CREATE TABLE center (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid NOT NULL DEFAULT current_tenant_id(),
            organization_id uuid NOT NULL,
            name            text NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, organization_id) REFERENCES organization (tenant_id, id)
        );

        CREATE TABLE donation_offer (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    uuid NOT NULL DEFAULT current_tenant_id(),
            donor_id     uuid NOT NULL,
            category     text NOT NULL,
            quantity     numeric(12, 3) NOT NULL CHECK (quantity > 0),
            unit         text NOT NULL CHECK (unit IN ('kg', 'l', 'pcs')),
            -- FR-012: use_by = never after the date; best_before = per country rule (FR-017).
            date_kind    text NOT NULL CHECK (date_kind IN ('use_by', 'best_before')),
            expires_on   date NOT NULL,
            storage      text NOT NULL CHECK (storage IN ('ambient', 'chilled', 'frozen')),
            pickup_from  timestamptz NOT NULL,
            pickup_until timestamptz NOT NULL,
            status       text NOT NULL DEFAULT 'draft' CHECK (status IN (
                             'draft', 'available', 'reserved', 'collected',
                             'delivered', 'expired', 'cancelled')),
            -- FR-016: every transition matches the version it read, then bumps it.
            version      integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            CHECK (pickup_until > pickup_from),
            FOREIGN KEY (tenant_id, donor_id) REFERENCES organization (tenant_id, id)
        );
        CREATE INDEX donation_offer_tenant_status ON donation_offer (tenant_id, status);

        -- FR-004: append-only. The app role gets SELECT and INSERT only.
        CREATE TABLE audit_event (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            occurred_at    timestamptz NOT NULL DEFAULT now(),
            actor          text NOT NULL,
            actor_role     text NOT NULL,
            action         text NOT NULL,
            object_type    text NOT NULL,
            object_id      uuid,
            outcome        text NOT NULL CHECK (outcome IN ('success', 'denied', 'failed')),
            correlation_id text NOT NULL,
            details        jsonb NOT NULL DEFAULT '{}'
        );
        CREATE INDEX audit_event_tenant_time ON audit_event (tenant_id, occurred_at);
        """
    )

    # RLS (ADR-003). Not FORCEd: the owner (secondchance_migrator) bypasses it, the app role never does.
    op.execute(
        """
        ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tenant USING (id = current_tenant_id());

        ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY audit_read ON audit_event FOR SELECT
            USING (tenant_id = current_tenant_id());
        CREATE POLICY audit_append ON audit_event FOR INSERT
            WITH CHECK (tenant_id = current_tenant_id());
        """
    )
    for table in TENANT_TABLES:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_tenant_id())
                WITH CHECK (tenant_id = current_tenant_id());
            """
        )

    op.execute(
        f"""
        GRANT SELECT ON tenant TO {APP_ROLE};
        GRANT SELECT, INSERT, UPDATE ON {", ".join(TENANT_TABLES)} TO {APP_ROLE};
        GRANT SELECT, INSERT ON audit_event TO {APP_ROLE};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE audit_event, donation_offer, center, organization, tenant;
        DROP FUNCTION current_tenant_id();
        """
    )
