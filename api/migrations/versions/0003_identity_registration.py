"""Identity and registration: memberships as the source of authorization (ADR-017).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APP_ROLE = "secondchance_app"
ROLES = ("donor", "coordinator", "volunteer", "center_staff", "org_admin", "platform_admin")

COMMENTS = {
    ("tenant", "status"): "pii:none; pending until a platform admin verifies the NGO",
    ("tenant", "kind"): "pii:none; network (an NGO) or platform (public knowledge, admins)",
    ("organization", "status"): "pii:none; pending until the network approves the donor",
    ("organization", "donor_type"): "pii:none; kind of donor business",
    ("membership", "id"): "pii:none; membership identifier",
    ("membership", "subject"): "pii:personal; OIDC subject pseudonym of the member",
    ("membership", "tenant_id"): "pii:none; network the member belongs to (RLS)",
    ("membership", "organization_id"): "pii:none; organisation the member acts for",
    ("membership", "role"): "pii:none; role inside the network (RBAC)",
    ("membership", "status"): "pii:none; pending, active, suspended or rejected",
    ("membership", "decided_by"): "pii:personal; subject pseudonym of who approved or rejected",
    ("membership", "decided_at"): "pii:none; decision time",
    ("membership", "created_at"): "pii:none; registration time",
}


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE tenant
            ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK (status IN ('pending', 'active', 'suspended')),
            ADD COLUMN kind text NOT NULL DEFAULT 'network' CHECK (kind IN ('network', 'platform'));

        ALTER TABLE organization
            ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK (status IN ('pending', 'active', 'suspended')),
            ADD COLUMN donor_type text CHECK (donor_type IN (
                'supermarket', 'restaurant', 'canteen', 'producer', 'wholesaler', 'other')),
            ADD CHECK (kind = 'donor' OR donor_type IS NULL);

        -- ADR-017: who may act where. Tokens only prove the subject; this table decides.
        CREATE TABLE membership (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            subject         text NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
            tenant_id       uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            organization_id uuid,
            role            text NOT NULL CHECK (role IN ({", ".join(_literal(r) for r in ROLES)})),
            status          text NOT NULL DEFAULT 'pending' CHECK (status IN (
                                'pending', 'active', 'suspended', 'rejected')),
            decided_by      text,
            decided_at      timestamptz,
            created_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (subject, tenant_id),
            FOREIGN KEY (tenant_id, organization_id) REFERENCES organization (tenant_id, id)
        );
        CREATE INDEX membership_subject ON membership (subject);
        ALTER TABLE membership ENABLE ROW LEVEL SECURITY;
        -- Two permissive policies, OR-ed: a subject reads its own memberships in any network
        -- (needed before a tenant is known); everything else stays inside the tenant.
        CREATE POLICY membership_self ON membership FOR SELECT
            USING (subject = current_setting('app.subject', true));
        CREATE POLICY tenant_isolation ON membership
            USING (tenant_id = current_tenant_id())
            WITH CHECK (tenant_id = current_tenant_id());

        -- Policies are OR-ed: the 0001 policy covered ALL commands, so it would let an INSERT
        -- create an active tenant. It becomes SELECT-only and each write gets its own policy.
        DROP POLICY tenant_isolation ON tenant;
        CREATE POLICY tenant_isolation ON tenant FOR SELECT USING (id = current_tenant_id());
        -- Registration creates a pending network inside its own new tenant context, and
        -- nothing else: the app can never create an active tenant or a platform tenant.
        CREATE POLICY tenant_register ON tenant FOR INSERT
            WITH CHECK (id = current_tenant_id() AND status = 'pending' AND kind = 'network');
        CREATE POLICY tenant_update ON tenant FOR UPDATE
            USING (id = current_tenant_id()) WITH CHECK (id = current_tenant_id());

        -- Guards on what the API role may change; owner and maintenance jobs are trusted.
        -- app.role and app.subject come from the membership the API resolved (ADR-017).
        CREATE FUNCTION guard_tenant_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user <> '{APP_ROLE}' THEN RETURN NEW; END IF;
            IF NEW.status IS DISTINCT FROM OLD.status
               AND current_setting('app.role', true) IS DISTINCT FROM 'platform_admin' THEN
                RAISE EXCEPTION 'only a platform admin changes a network status' USING ERRCODE = '42501';
            END IF;
            IF NEW.experiments_enabled IS DISTINCT FROM OLD.experiments_enabled
               AND current_setting('app.role', true) NOT IN ('org_admin', 'platform_admin') THEN
                RAISE EXCEPTION 'only an admin changes the experiments opt-in' USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_tenant_update BEFORE UPDATE ON tenant
            FOR EACH ROW EXECUTE FUNCTION guard_tenant_update();

        CREATE FUNCTION guard_organization_status() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user <> '{APP_ROLE}' THEN RETURN NEW; END IF;
            IF (TG_OP = 'INSERT' AND NEW.status <> 'pending'
                    AND current_setting('app.role', true) NOT IN ('org_admin', 'platform_admin'))
               OR (TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status
                    AND current_setting('app.role', true) NOT IN ('org_admin', 'platform_admin')) THEN
                RAISE EXCEPTION 'only an admin activates an organisation' USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_organization_status BEFORE INSERT OR UPDATE ON organization
            FOR EACH ROW EXECUTE FUNCTION guard_organization_status();

        CREATE FUNCTION guard_membership() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            actor_role text := current_setting('app.role', true);
            actor text := current_setting('app.subject', true);
            is_admin boolean := coalesce(current_setting('app.role', true), '') IN ('org_admin', 'platform_admin');
        BEGIN
            IF current_user <> '{APP_ROLE}' THEN RETURN NEW; END IF;
            IF NEW.role = 'platform_admin' AND actor_role IS DISTINCT FROM 'platform_admin' THEN
                RAISE EXCEPTION 'only a platform admin grants platform_admin' USING ERRCODE = '42501';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'pending' THEN
                    RAISE EXCEPTION 'new memberships start pending' USING ERRCODE = '42501';
                END IF;
                -- Self-registration: only for yourself, only as donor or NGO admin.
                IF NOT is_admin AND (NEW.subject IS DISTINCT FROM actor OR NEW.role NOT IN ('donor', 'org_admin')) THEN
                    RAISE EXCEPTION 'self-registration is limited to donor or NGO' USING ERRCODE = '42501';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.subject <> OLD.subject OR NEW.tenant_id <> OLD.tenant_id THEN
                RAISE EXCEPTION 'subject and tenant of a membership are immutable' USING ERRCODE = '42501';
            END IF;
            IF NOT is_admin OR NEW.subject = actor THEN
                RAISE EXCEPTION 'memberships are decided by another admin' USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_membership BEFORE INSERT OR UPDATE ON membership
            FOR EACH ROW EXECUTE FUNCTION guard_membership();

        -- The only cross-tenant reads, on purpose: owner-run views exposing public columns.
        CREATE VIEW network_directory AS
            SELECT id, name, country FROM tenant WHERE status = 'active' AND kind = 'network';
        -- Empty unless the transaction acts as platform_admin, whatever the caller queries.
        CREATE VIEW network_registration_queue AS
            SELECT t.id AS tenant_id, t.name, t.country, t.created_at, m.id AS membership_id
            FROM tenant t JOIN membership m ON m.tenant_id = t.id AND m.role = 'org_admin'
            WHERE t.status = 'pending' AND t.kind = 'network' AND m.status = 'pending'
              AND current_setting('app.role', true) = 'platform_admin';

        GRANT INSERT ON tenant TO {APP_ROLE};
        GRANT UPDATE (status, experiments_enabled) ON tenant TO {APP_ROLE};
        GRANT SELECT, INSERT, UPDATE ON membership TO {APP_ROLE};
        GRANT SELECT ON network_directory, network_registration_queue TO {APP_ROLE};
        """
    )
    op.execute(
        "\n".join(
            f"COMMENT ON COLUMN {table}.{column} IS {_literal(comment)};" for (table, column), comment in COMMENTS.items()
        )
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW network_registration_queue, network_directory;
        DROP TABLE membership;
        DROP FUNCTION guard_membership();
        DROP TRIGGER guard_organization_status ON organization;
        DROP FUNCTION guard_organization_status();
        DROP TRIGGER guard_tenant_update ON tenant;
        DROP FUNCTION guard_tenant_update();
        DROP POLICY tenant_update ON tenant;
        DROP POLICY tenant_register ON tenant;
        DROP POLICY tenant_isolation ON tenant;
        CREATE POLICY tenant_isolation ON tenant USING (id = current_tenant_id());
        ALTER TABLE organization DROP COLUMN donor_type, DROP COLUMN status;
        ALTER TABLE tenant DROP COLUMN kind, DROP COLUMN status;
        """
    )
