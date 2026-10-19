"""Operations: centre management, matching runs, approved allocations, missions, notifications.

FR-003/FR-014 (centres, capacity, acceptance slots), FR-012/FR-017 (food rules per country),
FR-020/FR-021 (deterministic matching, OR-Tools), FR-022 (human approval bound to a content hash),
FR-023/FR-025 (mission life cycle, reassignment without duplicates), FR-026 (email and in-app
notifications through an outbox), FR-052/FR-053 (aggregated dashboard). Every new tenant table has
RLS; volunteers see only their missions and centre staff only their centre's deliveries. State
machines are enforced by triggers on the API role, whatever the application code does.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APP_ROLE = "secondchance_app"
MAINTENANCE_ROLE = "secondchance_maintenance"
CATEGORIES = ("dairy", "meat_fish", "fruit_vegetables", "bakery", "dry_goods", "frozen", "ready_meals", "beverages", "other")
STORAGE = ("ambient", "chilled", "frozen")
SELF_REGISTRATION_ROLES = ("donor", "org_admin", "volunteer", "center_staff", "coordinator")
MANAGERS = "('coordinator', 'org_admin')"


def _array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{v}'" for v in values) + "]::text[]"


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


N, P = "pii:none", "pii:personal"
COMMENTS = {
    "center": {
        "status": f"{N}; active or paused (paused centres receive no proposals)",
        "address": f"{N}; address of the receiving centre (an organisation site, not a person)",
        "location": f"{N}; centre coordinates for distance estimates (PostGIS)",
        "timezone": f"{N}; IANA time zone of the acceptance slots",
        "accepted_categories": f"{N}; food categories the centre accepts (FR-014)",
        "storage_capabilities": f"{N}; ambient, chilled and frozen storage available (FR-012)",
        "daily_capacity_kg": f"{N}; daily intake capacity in kg (FR-014)",
        "version": f"{N}; optimistic lock for configuration changes",
        "updated_at": f"{N}; last change",
    },
    "center_slot": {
        "id": f"{N}; slot identifier", "tenant_id": f"{N}; owning tenant (RLS)", "center_id": f"{N}; centre",
        "weekday": f"{N}; ISO weekday, 1 is Monday", "opens": f"{N}; local opening time",
        "closes": f"{N}; local closing time",
    },
    "organization": {"location": f"{N}; pickup coordinates of a donor or NGO site (PostGIS)"},
    "membership": {
        "center_id": f"{N}; centre a centre-staff member acts for, set by an admin",
        "display_name": f"{P}; name the member chose so coordinators can recognise them",
    },
    "food_rule": {
        "country": f"{N}; country the rule applies to", "version": f"{N}; rule version (FR-017)",
        "best_before_grace_days": f"{N}; days a best_before product may still be distributed",
        "source": f"{N}; legal or procedural source of the rule", "valid_from": f"{N}; first day the version applies",
        "created_at": f"{N}; creation time",
    },
    "matching_run": {
        "id": f"{N}; run identifier and job id", "tenant_id": f"{N}; owning tenant (RLS)",
        "requested_by": f"{P}; OIDC subject pseudonym who started the run", "requested_role": f"{N}; role of the requester",
        "status": f"{N}; queued, running, succeeded, infeasible or failed", "solver": f"{N}; optimisation engine",
        "time_limit_ms": f"{N}; solver time limit (FR-021)", "random_seed": f"{N}; fixed seed for reproducible results",
        "input_sha256": f"{N}; checksum of the canonical solver input", "objective": f"{N}; objective value reached",
        "solver_status": f"{N}; CP-SAT status", "stats": f"{N}; counts and infeasibility reasons per offer",
        "error_category": f"{N}; failure category, never a message", "attempt": f"{N}; worker claims so far",
        "lease_until": f"{N}; worker claim expiry", "correlation_id": f"{N}; request correlation",
        "created_at": f"{N}; creation time", "started_at": f"{N}; solver start", "finished_at": f"{N}; completion time",
    },
    "allocation_proposal": {
        "id": f"{N}; proposal identifier", "tenant_id": f"{N}; owning tenant (RLS)", "run_id": f"{N}; matching run",
        "offer_id": f"{N}; proposed offer", "offer_version": f"{N}; offer version the solver read (FR-016)",
        "center_id": f"{N}; proposed centre", "quantity": f"{N}; quantity to move", "unit": f"{N}; unit of quantity",
        "load_kg": f"{N}; estimated load against capacity", "score": f"{N}; objective contribution",
        "distance_km": f"{N}; estimated road distance", "deliver_after": f"{N}; start of the delivery slot",
        "deliver_before": f"{N}; end of the delivery slot", "explanation": f"{N}; satisfied constraints and objective terms",
        "alternatives": f"{N}; other feasible centres, ranked", "content_sha256": f"{N}; checksum the approver must confirm (FR-022)",
        "status": f"{N}; proposed, approved, rejected, superseded or expired",
        "decided_by": f"{P}; OIDC subject pseudonym of the approver", "decided_at": f"{N}; decision time",
        "decision_reason": f"{N}; rejection reason code", "approved_center_id": f"{N}; centre chosen at approval",
        "created_at": f"{N}; creation time",
    },
    "mission": {
        "id": f"{N}; mission identifier", "tenant_id": f"{N}; owning tenant (RLS)",
        "proposal_id": f"{N}; approved proposal (FR-022)", "offer_id": f"{N}; offer to move", "center_id": f"{N}; destination centre",
        "volunteer_subject": f"{P}; OIDC subject pseudonym of the assigned volunteer",
        "status": f"{N}; assigned, accepted, picked_up, delivered, failed or cancelled (FR-023)",
        "version": f"{N}; optimistic lock", "reassignments": f"{N}; times the mission was reassigned (FR-025)",
        "failure_reason": f"{N}; failure reason code", "quantity": f"{N}; quantity to move", "unit": f"{N}; unit of quantity",
        "deliver_after": f"{N}; start of the delivery slot", "deliver_before": f"{N}; end of the delivery slot",
        "receipt": f"{N}; centre confirmation: confirmed or exception", "receipt_reason": f"{N}; exception reason code",
        "received_quantity": f"{N}; quantity the centre received", "created_by": f"{P}; OIDC subject pseudonym of the approver",
        "created_at": f"{N}; creation time", "updated_at": f"{N}; last change", "accepted_at": f"{N}; acceptance time",
        "picked_up_at": f"{N}; pickup time", "delivered_at": f"{N}; delivery time", "received_at": f"{N}; centre confirmation time",
    },
    "mission_event": {
        "id": f"{N}; event identifier", "tenant_id": f"{N}; owning tenant (RLS)", "mission_id": f"{N}; mission",
        "from_status": f"{N}; status before", "to_status": f"{N}; status after",
        "actor": f"{P}; OIDC subject pseudonym of who acted", "actor_role": f"{N}; role at the time of the action",
        "reason": f"{N}; reason code", "idempotency_key": f"{N}; client key that makes a retry a no-op (FR-027)",
        "occurred_at": f"{N}; event time",
    },
    "notification": {
        "id": f"{N}; notification identifier", "tenant_id": f"{N}; owning tenant (RLS)",
        "recipient": f"{P}; OIDC subject pseudonym of the recipient", "kind": f"{N}; notification type",
        "object_type": f"{N}; referenced object type", "object_id": f"{N}; referenced object",
        "created_at": f"{N}; creation time", "read_at": f"{N}; time the recipient read it",
    },
    "notification_delivery": {
        "id": f"{N}; delivery identifier", "tenant_id": f"{N}; owning tenant (RLS)", "notification_id": f"{N}; notification",
        "channel": f"{N}; delivery channel", "status": f"{N}; pending or queued (outbox)",
        "language": f"{N}; language of the message, from the network country", "attempts": f"{N}; queue hand-offs",
        "created_at": f"{N}; creation time", "queued_at": f"{N}; last hand-off to the notify queue",
    },
}

GUARD_MEMBERSHIP = """
CREATE OR REPLACE FUNCTION guard_membership() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    actor_role text := current_setting('app.role', true);
    actor text := current_setting('app.subject', true);
    is_admin boolean := coalesce(current_setting('app.role', true), '') IN ('org_admin', 'platform_admin');
BEGIN
    IF current_user <> '{app}' THEN RETURN NEW; END IF;
    IF NEW.role = 'platform_admin' AND actor_role IS DISTINCT FROM 'platform_admin' THEN
        RAISE EXCEPTION 'only a platform admin grants platform_admin' USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'pending' THEN
            RAISE EXCEPTION 'new memberships start pending' USING ERRCODE = '42501';
        END IF;
        -- Self-registration: only for yourself, only with the roles a newcomer may ask for.
        IF NOT is_admin AND (NEW.subject IS DISTINCT FROM actor OR NEW.role NOT IN ({roles})) THEN
            RAISE EXCEPTION 'self-registration is limited to {label}' USING ERRCODE = '42501';
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
"""


def upgrade() -> None:
    op.execute(
        f"""
        -- ---- Centres (FR-003, FR-014) ----
        ALTER TABLE center
            ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
            ADD COLUMN address text CHECK (length(address) <= 200),
            ADD COLUMN location geography(Point, 4326),
            ADD COLUMN timezone text NOT NULL DEFAULT 'UTC' CHECK (timezone ~ '^[A-Za-z_]+(/[A-Za-z0-9_+-]+)*$'),
            ADD COLUMN accepted_categories text[] NOT NULL DEFAULT {_array(CATEGORIES)}
                CHECK (cardinality(accepted_categories) > 0 AND accepted_categories <@ {_array(CATEGORIES)}),
            ADD COLUMN storage_capabilities text[] NOT NULL DEFAULT ARRAY['ambient']::text[]
                CHECK (cardinality(storage_capabilities) > 0 AND storage_capabilities <@ {_array(STORAGE)}),
            ADD COLUMN daily_capacity_kg numeric(10, 2) NOT NULL DEFAULT 200 CHECK (daily_capacity_kg > 0),
            ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
            ADD CONSTRAINT center_tenant_id_id_key UNIQUE (tenant_id, id),
            ADD CONSTRAINT center_name_length CHECK (length(name) BETWEEN 2 AND 120);

        CREATE TABLE center_slot (
            id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL DEFAULT current_tenant_id(),
            center_id uuid NOT NULL,
            weekday   smallint NOT NULL CHECK (weekday BETWEEN 1 AND 7),
            opens     time NOT NULL,
            closes    time NOT NULL,
            CHECK (closes > opens),
            UNIQUE (center_id, weekday, opens),
            FOREIGN KEY (tenant_id, center_id) REFERENCES center (tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX center_slot_center ON center_slot (tenant_id, center_id);

        ALTER TABLE organization ADD COLUMN location geography(Point, 4326);
        ALTER TABLE donation_offer ADD CONSTRAINT donation_offer_tenant_id_id_key UNIQUE (tenant_id, id);

        -- Centre staff act for one centre, chosen by an admin at approval; staff can name themselves.
        ALTER TABLE membership
            ADD COLUMN center_id uuid,
            ADD COLUMN display_name text CHECK (length(display_name) BETWEEN 1 AND 80),
            ADD CONSTRAINT membership_center_role CHECK (center_id IS NULL OR role = 'center_staff'),
            ADD CONSTRAINT membership_center_fk FOREIGN KEY (tenant_id, center_id) REFERENCES center (tenant_id, id);

        CREATE FUNCTION guard_membership_center() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user <> '{APP_ROLE}' THEN RETURN NEW; END IF;
            IF NEW.center_id IS NOT NULL
               AND coalesce(current_setting('app.role', true), '') NOT IN ('org_admin', 'platform_admin') THEN
                RAISE EXCEPTION 'only an admin assigns a centre' USING ERRCODE = '42501';
            END IF;
            IF NEW.role = 'center_staff' AND NEW.status = 'active' AND NEW.center_id IS NULL THEN
                RAISE EXCEPTION 'active centre staff need a centre' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_membership_center BEFORE INSERT OR UPDATE ON membership
            FOR EACH ROW EXECUTE FUNCTION guard_membership_center();

        -- ---- Food rules per country (FR-017): versioned configuration, no deployment to change ----
        CREATE TABLE food_rule (
            country                char(2) NOT NULL CHECK (country ~ '^[A-Z]{{2}}$'),
            version                integer NOT NULL CHECK (version >= 1),
            best_before_grace_days integer NOT NULL CHECK (best_before_grace_days BETWEEN 0 AND 365),
            source                 text NOT NULL CHECK (length(source) BETWEEN 3 AND 500),
            valid_from             date NOT NULL,
            created_at             timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (country, version)
        );

        -- ---- Matching runs and proposals (FR-020, FR-021, FR-022) ----
        CREATE TABLE matching_run (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            requested_by   text NOT NULL,
            requested_role text NOT NULL,
            status         text NOT NULL DEFAULT 'queued' CHECK (status IN (
                               'queued', 'running', 'succeeded', 'infeasible', 'failed')),
            solver         text NOT NULL DEFAULT 'cp_sat',
            time_limit_ms  integer NOT NULL CHECK (time_limit_ms BETWEEN 100 AND 60000),
            random_seed    integer NOT NULL DEFAULT 0,
            input_sha256   text CHECK (input_sha256 ~ '^[0-9a-f]{{64}}$'),
            objective      numeric,
            solver_status  text,
            stats          jsonb NOT NULL DEFAULT '{{}}',
            error_category text,
            attempt        integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            lease_until    timestamptz,
            correlation_id text NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            started_at     timestamptz,
            finished_at    timestamptz,
            UNIQUE (tenant_id, id)
        );
        CREATE INDEX matching_run_tenant_time ON matching_run (tenant_id, created_at DESC);

        CREATE TABLE allocation_proposal (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          uuid NOT NULL DEFAULT current_tenant_id(),
            run_id             uuid NOT NULL,
            offer_id           uuid NOT NULL,
            offer_version      integer NOT NULL CHECK (offer_version > 0),
            center_id          uuid NOT NULL,
            quantity           numeric(12, 3) NOT NULL CHECK (quantity > 0),
            unit               text NOT NULL CHECK (unit IN ('kg', 'l', 'pcs')),
            load_kg            numeric(12, 3) NOT NULL CHECK (load_kg > 0),
            score              integer NOT NULL,
            distance_km        numeric(8, 2),
            deliver_after      timestamptz NOT NULL,
            deliver_before     timestamptz NOT NULL,
            explanation        jsonb NOT NULL,
            alternatives       jsonb NOT NULL DEFAULT '[]',
            content_sha256     text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
            status             text NOT NULL DEFAULT 'proposed' CHECK (status IN (
                                   'proposed', 'approved', 'rejected', 'superseded', 'expired')),
            decided_by         text,
            decided_at         timestamptz,
            decision_reason    text CHECK (decision_reason ~ '^[a-z_]{{3,40}}$'),
            approved_center_id uuid,
            created_at         timestamptz NOT NULL DEFAULT now(),
            CHECK (deliver_before > deliver_after),
            CHECK ((status IN ('approved', 'rejected')) = (decided_by IS NOT NULL)),
            CHECK ((status = 'approved') = (approved_center_id IS NOT NULL)),
            UNIQUE (tenant_id, id),
            UNIQUE (run_id, offer_id),
            FOREIGN KEY (tenant_id, run_id) REFERENCES matching_run (tenant_id, id),
            FOREIGN KEY (tenant_id, offer_id) REFERENCES donation_offer (tenant_id, id),
            FOREIGN KEY (tenant_id, center_id) REFERENCES center (tenant_id, id),
            FOREIGN KEY (tenant_id, approved_center_id) REFERENCES center (tenant_id, id)
        );
        CREATE INDEX allocation_proposal_open ON allocation_proposal (tenant_id, status, created_at);
        CREATE INDEX allocation_proposal_offer ON allocation_proposal (offer_id);

        -- What the approver saw is what gets executed: content is immutable, decisions are one-way.
        CREATE FUNCTION guard_allocation_proposal() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            actor_role text := coalesce(current_setting('app.role', true), '');
        BEGIN
            IF current_user <> '{APP_ROLE}' THEN RETURN NEW; END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'proposed' OR actor_role <> 'solver' THEN
                    RAISE EXCEPTION 'proposals come from the solver, pending' USING ERRCODE = '42501';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.run_id, NEW.offer_id, NEW.offer_version, NEW.center_id, NEW.quantity, NEW.unit, NEW.load_kg,
                NEW.score, NEW.deliver_after, NEW.deliver_before, NEW.explanation, NEW.alternatives, NEW.content_sha256)
               IS DISTINCT FROM
               (OLD.run_id, OLD.offer_id, OLD.offer_version, OLD.center_id, OLD.quantity, OLD.unit, OLD.load_kg,
                OLD.score, OLD.deliver_after, OLD.deliver_before, OLD.explanation, OLD.alternatives, OLD.content_sha256) THEN
                RAISE EXCEPTION 'proposal content is immutable' USING ERRCODE = '42501';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF OLD.status <> 'proposed' THEN
                    RAISE EXCEPTION 'proposal already decided' USING ERRCODE = '42501';
                END IF;
                IF NEW.status IN ('approved', 'rejected') AND (actor_role NOT IN {MANAGERS}
                   OR NEW.decided_by IS DISTINCT FROM current_setting('app.subject', true)) THEN
                    RAISE EXCEPTION 'only a coordinator or admin decides, in their own name' USING ERRCODE = '42501';
                END IF;
                IF NEW.status IN ('superseded', 'expired') AND actor_role NOT IN ('solver', 'coordinator', 'org_admin') THEN
                    RAISE EXCEPTION 'only the solver or an operator retires a proposal' USING ERRCODE = '42501';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_allocation_proposal BEFORE INSERT OR UPDATE ON allocation_proposal
            FOR EACH ROW EXECUTE FUNCTION guard_allocation_proposal();

        -- ---- Missions (FR-022, FR-023, FR-025) ----
        CREATE TABLE mission (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         uuid NOT NULL DEFAULT current_tenant_id(),
            proposal_id       uuid NOT NULL UNIQUE,
            offer_id          uuid NOT NULL,
            center_id         uuid NOT NULL,
            volunteer_subject text NOT NULL CHECK (length(volunteer_subject) BETWEEN 1 AND 255),
            status            text NOT NULL DEFAULT 'assigned' CHECK (status IN (
                                  'assigned', 'accepted', 'picked_up', 'delivered', 'failed', 'cancelled')),
            version           integer NOT NULL DEFAULT 1 CHECK (version > 0),
            reassignments     integer NOT NULL DEFAULT 0 CHECK (reassignments >= 0),
            failure_reason    text CHECK (failure_reason ~ '^[a-z_]{{3,40}}$'),
            quantity          numeric(12, 3) NOT NULL CHECK (quantity > 0),
            unit              text NOT NULL CHECK (unit IN ('kg', 'l', 'pcs')),
            deliver_after     timestamptz NOT NULL,
            deliver_before    timestamptz NOT NULL,
            receipt           text CHECK (receipt IN ('confirmed', 'exception')),
            receipt_reason    text CHECK (receipt_reason ~ '^[a-z_]{{3,40}}$'),
            received_quantity numeric(12, 3) CHECK (received_quantity >= 0),
            created_by        text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),
            accepted_at       timestamptz,
            picked_up_at      timestamptz,
            delivered_at      timestamptz,
            received_at       timestamptz,
            CHECK (deliver_before > deliver_after),
            CHECK ((receipt IS NULL) = (received_at IS NULL)),
            CHECK (receipt IS NULL OR received_quantity IS NOT NULL),
            CHECK (status <> 'failed' OR failure_reason IS NOT NULL),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, proposal_id) REFERENCES allocation_proposal (tenant_id, id),
            FOREIGN KEY (tenant_id, offer_id) REFERENCES donation_offer (tenant_id, id),
            FOREIGN KEY (tenant_id, center_id) REFERENCES center (tenant_id, id)
        );
        -- One live mission per offer: a failure is handled by reassignment, never by a duplicate.
        CREATE UNIQUE INDEX mission_one_live_per_offer ON mission (offer_id) WHERE status <> 'cancelled';
        CREATE INDEX mission_volunteer ON mission (tenant_id, volunteer_subject, status);
        CREATE INDEX mission_center ON mission (tenant_id, center_id, deliver_after);

        CREATE FUNCTION guard_mission() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            actor_role text := coalesce(current_setting('app.role', true), '');
            actor text := current_setting('app.subject', true);
            moves text := OLD.status || '>' || NEW.status;
        BEGIN
            IF current_user <> '{APP_ROLE}' THEN RETURN NEW; END IF;
            IF TG_OP = 'INSERT' THEN
                IF actor_role NOT IN {MANAGERS} OR NEW.status <> 'assigned' OR NEW.created_by IS DISTINCT FROM actor THEN
                    RAISE EXCEPTION 'missions are created assigned, by the approving operator' USING ERRCODE = '42501';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.proposal_id, NEW.offer_id, NEW.center_id, NEW.quantity, NEW.unit, NEW.created_by, NEW.created_at)
               IS DISTINCT FROM
               (OLD.proposal_id, OLD.offer_id, OLD.center_id, OLD.quantity, OLD.unit, OLD.created_by, OLD.created_at) THEN
                RAISE EXCEPTION 'mission identity is immutable' USING ERRCODE = '42501';
            END IF;
            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'every mission change bumps the version once' USING ERRCODE = '42501';
            END IF;
            IF actor_role = 'volunteer' THEN
                IF OLD.volunteer_subject IS DISTINCT FROM actor OR NEW.volunteer_subject IS DISTINCT FROM OLD.volunteer_subject
                   OR moves NOT IN ('assigned>accepted', 'accepted>picked_up', 'picked_up>delivered',
                                    'assigned>failed', 'accepted>failed', 'picked_up>failed')
                   OR NEW.receipt IS DISTINCT FROM OLD.receipt THEN
                    RAISE EXCEPTION 'volunteers move only their own missions forward' USING ERRCODE = '42501';
                END IF;
            ELSIF actor_role = 'center_staff' THEN
                IF NEW.volunteer_subject IS DISTINCT FROM OLD.volunteer_subject OR OLD.receipt IS NOT NULL
                   OR NEW.receipt IS NULL OR OLD.status NOT IN ('picked_up', 'delivered')
                   OR NEW.status NOT IN ('delivered', 'failed') THEN
                    RAISE EXCEPTION 'centre staff only confirm or contest a receipt' USING ERRCODE = '42501';
                END IF;
            ELSIF actor_role IN {MANAGERS} THEN
                IF NEW.volunteer_subject IS DISTINCT FROM OLD.volunteer_subject OR NEW.reassignments <> OLD.reassignments THEN
                    IF OLD.status NOT IN ('assigned', 'accepted', 'failed') OR OLD.picked_up_at IS NOT NULL
                       OR NEW.status <> 'assigned' OR NEW.reassignments <> OLD.reassignments + 1 THEN
                        RAISE EXCEPTION 'reassignment is possible only before pickup' USING ERRCODE = '42501';
                    END IF;
                ELSIF NEW.status IS DISTINCT FROM OLD.status
                      AND moves NOT IN ('assigned>cancelled', 'accepted>cancelled', 'failed>cancelled',
                                        'picked_up>cancelled', 'assigned>failed', 'accepted>failed', 'picked_up>failed',
                                        'picked_up>delivered', 'delivered>failed') THEN
                    RAISE EXCEPTION 'transition not allowed' USING ERRCODE = '42501';
                END IF;
            ELSE
                RAISE EXCEPTION 'role may not change missions' USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_mission BEFORE INSERT OR UPDATE ON mission
            FOR EACH ROW EXECUTE FUNCTION guard_mission();

        CREATE TABLE mission_event (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid NOT NULL DEFAULT current_tenant_id(),
            mission_id      uuid NOT NULL,
            from_status     text,
            to_status       text NOT NULL,
            actor           text NOT NULL,
            actor_role      text NOT NULL,
            reason          text CHECK (reason ~ '^[a-z_]{{3,40}}$'),
            idempotency_key text CHECK (length(idempotency_key) BETWEEN 8 AND 128),
            occurred_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (mission_id, idempotency_key),
            FOREIGN KEY (tenant_id, mission_id) REFERENCES mission (tenant_id, id)
        );
        CREATE INDEX mission_event_mission ON mission_event (mission_id, occurred_at);

        -- ---- Offer transitions in the database (threat model: arbitrary status via direct UPDATE) ----
        CREATE FUNCTION guard_donation_offer() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user <> '{APP_ROLE}' OR NEW.status IS NOT DISTINCT FROM OLD.status THEN RETURN NEW; END IF;
            IF OLD.status || '>' || NEW.status NOT IN (
                'draft>available', 'draft>cancelled', 'available>reserved', 'available>expired', 'available>cancelled',
                'reserved>available', 'reserved>collected', 'reserved>cancelled', 'collected>delivered',
                'collected>cancelled') THEN
                RAISE EXCEPTION 'offer transition % > % not allowed', OLD.status, NEW.status USING ERRCODE = '42501';
            END IF;
            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'an offer transition bumps the version' USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_donation_offer BEFORE UPDATE ON donation_offer
            FOR EACH ROW EXECUTE FUNCTION guard_donation_offer();

        -- ---- Notifications (FR-026): in-app rows plus an email outbox ----
        CREATE TABLE notification (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            recipient   text NOT NULL CHECK (length(recipient) BETWEEN 1 AND 255),
            kind        text NOT NULL CHECK (kind ~ '^[a-z_]{{3,40}}$'),
            object_type text NOT NULL CHECK (object_type IN ('mission', 'matching_run', 'allocation_proposal')),
            object_id   uuid NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            read_at     timestamptz,
            UNIQUE (tenant_id, id)
        );
        CREATE INDEX notification_inbox ON notification (tenant_id, recipient, created_at DESC);

        CREATE TABLE notification_delivery (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid NOT NULL DEFAULT current_tenant_id(),
            notification_id uuid NOT NULL,
            channel         text NOT NULL DEFAULT 'email' CHECK (channel IN ('email')),
            status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'queued')),
            language        text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'da', 'pl', 'it')),
            attempts        integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            created_at      timestamptz NOT NULL DEFAULT now(),
            queued_at       timestamptz,
            UNIQUE (notification_id, channel),
            FOREIGN KEY (tenant_id, notification_id) REFERENCES notification (tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX notification_delivery_pending ON notification_delivery (status, created_at) WHERE status = 'pending';
        """
    )
    roles = ", ".join(_literal(r) for r in SELF_REGISTRATION_ROLES)
    op.execute(GUARD_MEMBERSHIP.format(app=APP_ROLE, roles=roles,
                                       label="donor, NGO, volunteer, centre staff or coordinator"))

    # ---- RLS ----
    op.execute(
        f"""
        ALTER TABLE center_slot ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON center_slot
            USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

        ALTER TABLE matching_run ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON matching_run
            USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

        ALTER TABLE allocation_proposal ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON allocation_proposal
            USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

        -- Operators see the network's missions; volunteers their own; centre staff their centre's.
        ALTER TABLE mission ENABLE ROW LEVEL SECURITY;
        CREATE POLICY mission_visible ON mission FOR SELECT USING (
            tenant_id = current_tenant_id() AND (
                current_setting('app.role', true) IN ('coordinator', 'org_admin', 'solver')
                OR (current_setting('app.role', true) = 'volunteer'
                    AND volunteer_subject = current_setting('app.subject', true))
                OR (current_setting('app.role', true) = 'center_staff' AND center_id IN (
                    SELECT m.center_id FROM membership m
                    WHERE m.subject = current_setting('app.subject', true) AND m.tenant_id = current_tenant_id()
                      AND m.role = 'center_staff' AND m.status = 'active'))));
        CREATE POLICY mission_insert ON mission FOR INSERT WITH CHECK (tenant_id = current_tenant_id());
        CREATE POLICY mission_update ON mission FOR UPDATE
            USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

        ALTER TABLE mission_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY mission_event_visible ON mission_event FOR SELECT USING (
            tenant_id = current_tenant_id() AND mission_id IN (SELECT id FROM mission));
        CREATE POLICY mission_event_append ON mission_event FOR INSERT WITH CHECK (tenant_id = current_tenant_id());

        -- A notification belongs to its recipient only, even inside the network.
        ALTER TABLE notification ENABLE ROW LEVEL SECURITY;
        CREATE POLICY notification_inbox ON notification FOR SELECT USING (
            tenant_id = current_tenant_id() AND recipient = current_setting('app.subject', true));
        CREATE POLICY notification_create ON notification FOR INSERT WITH CHECK (tenant_id = current_tenant_id());
        CREATE POLICY notification_read ON notification FOR UPDATE
            USING (tenant_id = current_tenant_id() AND recipient = current_setting('app.subject', true))
            WITH CHECK (tenant_id = current_tenant_id() AND recipient = current_setting('app.subject', true));

        ALTER TABLE notification_delivery ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON notification_delivery
            USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

        -- Scheduled jobs: retention, outbox recovery, stale runs and expired offers (migration 0005 pattern).
        CREATE POLICY maintenance_jobs ON notification_delivery FOR ALL TO {MAINTENANCE_ROLE} USING (true);
        CREATE POLICY maintenance_jobs ON notification FOR ALL TO {MAINTENANCE_ROLE} USING (true);
        CREATE POLICY maintenance_jobs ON matching_run FOR ALL TO {MAINTENANCE_ROLE} USING (true);
        CREATE POLICY maintenance_jobs ON allocation_proposal FOR ALL TO {MAINTENANCE_ROLE} USING (true);
        CREATE POLICY maintenance_jobs ON mission FOR ALL TO {MAINTENANCE_ROLE} USING (true);
        CREATE POLICY maintenance_jobs ON mission_event FOR ALL TO {MAINTENANCE_ROLE} USING (true);
        CREATE POLICY maintenance_jobs ON donation_offer FOR ALL TO {MAINTENANCE_ROLE} USING (true);

        GRANT SELECT, INSERT, UPDATE, DELETE ON center_slot TO {APP_ROLE};
        GRANT SELECT ON food_rule TO {APP_ROLE};
        GRANT SELECT, INSERT, UPDATE ON matching_run, allocation_proposal, mission TO {APP_ROLE};
        GRANT SELECT, INSERT ON mission_event TO {APP_ROLE};
        GRANT SELECT, INSERT ON notification TO {APP_ROLE};
        GRANT UPDATE (read_at) ON notification TO {APP_ROLE};
        GRANT SELECT, INSERT ON notification_delivery TO {APP_ROLE};
        GRANT UPDATE (status, attempts, queued_at) ON notification_delivery TO {APP_ROLE};

        GRANT SELECT, DELETE ON notification, mission_event, mission, allocation_proposal, matching_run TO {MAINTENANCE_ROLE};
        GRANT SELECT, UPDATE, DELETE ON notification_delivery TO {MAINTENANCE_ROLE};
        -- Offer expiry reads only the columns it decides on: never categories, quantities or donors.
        GRANT SELECT (id, status, version, pickup_until, date_kind, expires_on) ON donation_offer TO {MAINTENANCE_ROLE};
        GRANT UPDATE (status, version, updated_at) ON donation_offer TO {MAINTENANCE_ROLE};
        GRANT UPDATE (status) ON allocation_proposal TO {MAINTENANCE_ROLE};
        """
    )

    # Conservative synthetic defaults, to validate with the competent authority before a pilot (PRD 5.2).
    op.execute(
        """
        INSERT INTO food_rule (country, version, best_before_grace_days, source, valid_from) VALUES
            ('IT', 1, 30, 'Synthetic demo rule after EU food donation guidelines 2017/C 361/01; validate before the pilot', '2026-01-01'),
            ('DK', 1, 14, 'Synthetic demo rule after EU food donation guidelines 2017/C 361/01; validate before the pilot', '2026-01-01'),
            ('PL', 1, 0, 'Conservative default: no distribution after best before until validated', '2026-01-01');
        """
    )
    op.execute(
        "\n".join(
            f"COMMENT ON COLUMN {table}.{column} IS {_literal(comment)};"
            for table, columns in COMMENTS.items()
            for column, comment in columns.items()
        )
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER guard_donation_offer ON donation_offer;
        DROP FUNCTION guard_donation_offer();
        DROP POLICY maintenance_jobs ON donation_offer;
        REVOKE UPDATE (status, version, updated_at) ON donation_offer FROM secondchance_maintenance;
        REVOKE SELECT ON donation_offer FROM secondchance_maintenance;
        DROP TABLE notification_delivery, notification, mission_event, mission, allocation_proposal, matching_run, food_rule;
        DROP FUNCTION guard_mission();
        DROP FUNCTION guard_allocation_proposal();
        DROP TRIGGER guard_membership_center ON membership;
        DROP FUNCTION guard_membership_center();
        ALTER TABLE membership DROP CONSTRAINT membership_center_fk, DROP CONSTRAINT membership_center_role,
            DROP COLUMN display_name, DROP COLUMN center_id;
        ALTER TABLE donation_offer DROP CONSTRAINT donation_offer_tenant_id_id_key;
        ALTER TABLE organization DROP COLUMN location;
        DROP TABLE center_slot;
        ALTER TABLE center DROP CONSTRAINT center_name_length, DROP CONSTRAINT center_tenant_id_id_key,
            DROP COLUMN updated_at, DROP COLUMN version, DROP COLUMN daily_capacity_kg, DROP COLUMN storage_capabilities,
            DROP COLUMN accepted_categories, DROP COLUMN timezone, DROP COLUMN location, DROP COLUMN address,
            DROP COLUMN status;
        """
    )
    op.execute(GUARD_MEMBERSHIP.format(app=APP_ROLE, roles="'donor', 'org_admin'", label="donor or NGO"))
