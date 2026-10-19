"""Agent runs and steps, shared agent memory, experiments, routing decisions, data classification.

ADR-010 (agents), ADR-011 (shared memory), ADR-013 (experiments), ADR-007 (routing shadow),
ADR-014 (every column classified for the GDPR data inventory).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "secondchance_app"
MAINTENANCE_ROLE = "secondchance_maintenance"
NEW_TENANT_TABLES = ("agent_run", "agent_step", "agent_memory", "experiment_exposure", "routing_decision")

NONE, PERSONAL = "pii:none", "pii:personal"

# ADR-014: every column says whether it holds personal data and why it exists.
# tests/test_privacy.py fails if a column is missing here or in a later migration.
COLUMN_CLASSIFICATION: dict[str, dict[str, str]] = {
    "tenant": {
        "id": f"{NONE}; tenant identifier",
        "name": f"{NONE}; organisation name (legal entity, not a person)",
        "country": f"{NONE}; country whose food rules apply (FR-017)",
        "created_at": f"{NONE}; provisioning time",
        "experiments_enabled": f"{NONE}; tenant opt-in to A/B experiments (ADR-013)",
    },
    "organization": {
        "id": f"{NONE}; organisation identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "name": f"{NONE}; organisation name (legal entity, not a person)",
        "kind": f"{NONE}; ngo or donor",
        "created_at": f"{NONE}; creation time",
    },
    "center": {
        "id": f"{NONE}; center identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "organization_id": f"{NONE}; operating organisation",
        "name": f"{NONE}; center name",
        "created_at": f"{NONE}; creation time",
    },
    "donation_offer": {
        "id": f"{NONE}; offer identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "donor_id": f"{NONE}; donor organisation",
        "category": f"{NONE}; food category",
        "quantity": f"{NONE}; offered quantity",
        "unit": f"{NONE}; unit of quantity",
        "date_kind": f"{NONE}; use_by or best_before (FR-012)",
        "expires_on": f"{NONE}; expiry date",
        "storage": f"{NONE}; storage condition",
        "pickup_from": f"{NONE}; pickup window start",
        "pickup_until": f"{NONE}; pickup window end",
        "status": f"{NONE}; lifecycle state (FR-013)",
        "version": f"{NONE}; optimistic lock (FR-016)",
        "created_at": f"{NONE}; creation time",
        "updated_at": f"{NONE}; last change",
    },
    "audit_event": {
        "id": f"{NONE}; event identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "occurred_at": f"{NONE}; event time",
        "actor": f"{PERSONAL}; OIDC subject pseudonym of the actor, accountability (FR-004)",
        "actor_role": f"{NONE}; role at the time of the action",
        "action": f"{NONE}; action name",
        "object_type": f"{NONE}; affected object type",
        "object_id": f"{NONE}; affected object",
        "outcome": f"{NONE}; success, denied or failed",
        "correlation_id": f"{NONE}; request correlation",
        "details": f"{PERSONAL}; event metadata, may reference people",
    },
    "agent_run": {
        "id": f"{NONE}; run identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "requested_by": f"{PERSONAL}; OIDC subject pseudonym who started the run",
        "requested_role": f"{NONE}; role the run acts with",
        "status": f"{NONE}; run state (ADR-010)",
        "max_steps": f"{NONE}; step budget",
        "max_tokens": f"{NONE}; token budget",
        "deadline_at": f"{NONE}; time budget",
        "steps_used": f"{NONE}; steps consumed",
        "tokens_used": f"{NONE}; tokens consumed",
        "correlation_id": f"{NONE}; request correlation",
        "version": f"{NONE}; optimistic lock",
        "created_at": f"{NONE}; creation time",
        "updated_at": f"{NONE}; last change",
    },
    "agent_step": {
        "id": f"{NONE}; step identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "run_id": f"{NONE}; parent run",
        "seq": f"{NONE}; position in the run, unique per run",
        "agent": f"{NONE}; agent that executes the step",
        "status": f"{NONE}; step state",
        "attempt": f"{NONE}; fencing token for at-least-once delivery",
        "lease_until": f"{NONE}; claim expiry for crash recovery",
        "model_id": f"{NONE}; model that answered (ADR-008)",
        "prompt_sha256": f"{NONE}; prompt template version (ADR-008)",
        "input_tokens": f"{NONE}; tokens in",
        "output_tokens": f"{NONE}; tokens out",
        "latency_ms": f"{NONE}; execution time",
        "error_category": f"{NONE}; failure category, never a message",
        "created_at": f"{NONE}; creation time",
        "finished_at": f"{NONE}; completion time",
    },
    "agent_memory": {
        "id": f"{NONE}; memory identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "scope": f"{NONE}; run, conversation or tenant (ADR-011)",
        "run_id": f"{NONE}; run for scope run",
        "subject": f"{PERSONAL}; OIDC subject pseudonym for scope conversation",
        "kind": f"{NONE}; task, finding, message or fact",
        "content": f"{PERSONAL}; text after PII redaction, may still mention people",
        "source": f"{NONE}; provenance: agent name or operator",
        "embedding": f"{PERSONAL}; vector derived from content",
        "embedding_model": f"{NONE}; model that produced the vector",
        "created_at": f"{NONE}; creation time",
        "expires_at": f"{NONE}; mandatory expiry (ADR-014)",
    },
    "experiment": {
        "key": f"{NONE}; experiment identifier",
        "surface": f"{NONE}; what the experiment may change (ADR-013)",
        "unit": f"{NONE}; randomisation unit",
        "variants": f"{NONE}; variant names and weights, first is control",
        "status": f"{NONE}; draft, running or stopped (kill switch)",
        "hypothesis": f"{NONE}; pre-registered hypothesis",
        "primary_metric": f"{NONE}; pre-registered primary metric",
        "guardrail_metrics": f"{NONE}; metrics that stop the experiment",
        "created_at": f"{NONE}; creation time",
    },
    "experiment_exposure": {
        "id": f"{NONE}; exposure identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "experiment_key": f"{NONE}; experiment",
        "variant": f"{NONE}; variant shown",
        "unit_hash": f"{PERSONAL}; sha256 pseudonym of the unit",
        "correlation_id": f"{NONE}; request correlation",
        "occurred_at": f"{NONE}; exposure time",
    },
    "routing_decision": {
        "id": f"{NONE}; decision identifier",
        "tenant_id": f"{NONE}; owning tenant (RLS)",
        "request_id": f"{NONE}; routed request, groups primary and shadow",
        "router": f"{NONE}; baseline or rizzo_flow (ADR-007)",
        "shadow": f"{NONE}; true when the decision was not used",
        "route": f"{NONE}; chosen workflow",
        "outcome": f"{NONE}; ok, escalate or error",
        "probability": f"{NONE}; top probability",
        "model_fingerprint": f"{NONE}; model build that decided",
        "latency_ms": f"{NONE}; decision time",
        "correlation_id": f"{NONE}; request correlation",
        "created_at": f"{NONE}; decision time",
    },
}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant ADD COLUMN experiments_enabled boolean NOT NULL DEFAULT false;

        -- ADR-010: one row per agent execution. Budgets are explicit; exceeding one is
        -- budget_exhausted, never success. The task text lives in agent_memory (7-day TTL).
        CREATE TABLE agent_run (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            requested_by   text NOT NULL,
            requested_role text NOT NULL,
            status         text NOT NULL DEFAULT 'queued' CHECK (status IN (
                               'queued', 'running', 'waiting_approval', 'succeeded',
                               'failed', 'budget_exhausted', 'cancelled')),
            max_steps      integer NOT NULL DEFAULT 12 CHECK (max_steps BETWEEN 1 AND 50),
            max_tokens     integer NOT NULL DEFAULT 60000 CHECK (max_tokens > 0),
            deadline_at    timestamptz NOT NULL DEFAULT now() + interval '10 minutes',
            steps_used     integer NOT NULL DEFAULT 0 CHECK (steps_used >= 0),
            tokens_used    integer NOT NULL DEFAULT 0 CHECK (tokens_used >= 0),
            correlation_id text NOT NULL,
            version        integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id)
        );

        -- A step is claimed with a lease and completed only by the attempt that claimed it,
        -- so an SQS redelivery or a crashed worker never runs a finished step twice.
        CREATE TABLE agent_step (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL DEFAULT current_tenant_id(),
            run_id         uuid NOT NULL,
            seq            integer NOT NULL CHECK (seq >= 1),
            agent          text NOT NULL CHECK (agent IN (
                               'supervisor', 'intake', 'knowledge', 'matching', 'compliance')),
            status         text NOT NULL DEFAULT 'pending' CHECK (status IN (
                               'pending', 'running', 'succeeded', 'failed')),
            attempt        integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            lease_until    timestamptz,
            model_id       text,
            prompt_sha256  text CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
            input_tokens   integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
            output_tokens  integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
            latency_ms     integer CHECK (latency_ms >= 0),
            error_category text,
            created_at     timestamptz NOT NULL DEFAULT now(),
            finished_at    timestamptz,
            UNIQUE (run_id, seq),
            FOREIGN KEY (tenant_id, run_id) REFERENCES agent_run (tenant_id, id)
        );

        -- ADR-011: memory shared by stateless agents. Every row expires; tenant-wide
        -- memory only comes from an operator, never from a model.
        CREATE TABLE agent_memory (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            scope           text NOT NULL CHECK (scope IN ('run', 'conversation', 'tenant')),
            run_id          uuid,
            subject         text,
            kind            text NOT NULL CHECK (kind IN ('task', 'finding', 'message', 'fact')),
            content         text NOT NULL CHECK (length(content) BETWEEN 1 AND 8000),
            source          text NOT NULL,
            embedding       vector(1024),
            embedding_model text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            expires_at      timestamptz NOT NULL,
            CHECK ((scope = 'run') = (run_id IS NOT NULL)),
            CHECK ((scope = 'conversation') = (subject IS NOT NULL)),
            CHECK (scope <> 'tenant' OR source = 'operator'),
            CHECK ((embedding IS NULL) = (embedding_model IS NULL)),
            CHECK (expires_at > created_at),
            FOREIGN KEY (tenant_id, run_id) REFERENCES agent_run (tenant_id, id)
        );
        CREATE INDEX agent_memory_run ON agent_memory (tenant_id, run_id, created_at);
        CREATE INDEX agent_memory_subject ON agent_memory (tenant_id, subject, created_at);
        CREATE INDEX agent_memory_expiry ON agent_memory (expires_at);
        CREATE INDEX agent_memory_embedding ON agent_memory
            USING hnsw (embedding vector_cosine_ops);

        -- ADR-013: platform-level, holds no personal data. Allocation, solver and food
        -- rules are not surfaces, so no experiment can change who receives aid.
        CREATE TABLE experiment (
            key               text PRIMARY KEY CHECK (key ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'),
            surface           text NOT NULL CHECK (surface IN (
                                  'ui', 'prompt', 'retrieval', 'routing', 'notification_copy')),
            unit              text NOT NULL CHECK (unit IN ('subject', 'tenant')),
            variants          jsonb NOT NULL CHECK (
                                  jsonb_typeof(variants) = 'array'
                                  AND jsonb_array_length(variants) BETWEEN 2 AND 10),
            status            text NOT NULL DEFAULT 'draft' CHECK (status IN (
                                  'draft', 'running', 'stopped')),
            hypothesis        text NOT NULL,
            primary_metric    text NOT NULL,
            guardrail_metrics text[] NOT NULL DEFAULT '{}',
            created_at        timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE experiment_exposure (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            experiment_key text NOT NULL REFERENCES experiment (key),
            variant        text NOT NULL,
            unit_hash      text NOT NULL CHECK (unit_hash ~ '^[0-9a-f]{64}$'),
            correlation_id text NOT NULL,
            occurred_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX experiment_exposure_key ON experiment_exposure (experiment_key, occurred_at);

        -- ADR-007: primary and shadow decisions side by side. Metadata only, never the text.
        CREATE TABLE routing_decision (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            request_id        uuid NOT NULL,
            router            text NOT NULL CHECK (router IN ('baseline', 'rizzo_flow')),
            shadow            boolean NOT NULL,
            route             text,
            outcome           text NOT NULL CHECK (outcome IN ('ok', 'escalate', 'error')),
            probability       real CHECK (probability BETWEEN 0 AND 1),
            model_fingerprint text,
            latency_ms        integer NOT NULL CHECK (latency_ms >= 0),
            correlation_id    text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            UNIQUE (request_id, router),
            -- escalate and error may keep the best guess, for the shadow comparison.
            CHECK (outcome <> 'ok' OR route IS NOT NULL)
        );
        """
    )

    for table in NEW_TENANT_TABLES:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_tenant_id())
                WITH CHECK (tenant_id = current_tenant_id());
            """
        )

    # Append-only where history matters; mutable only where a state machine needs it.
    op.execute(
        f"""
        GRANT SELECT, INSERT, UPDATE ON agent_run, agent_step TO {APP_ROLE};
        GRANT SELECT, INSERT ON agent_memory, experiment_exposure, routing_decision TO {APP_ROLE};
        GRANT SELECT ON experiment TO {APP_ROLE};

        -- Scheduled jobs (retention, erasure, re-queue), see db/bootstrap.sql.
        GRANT SELECT, DELETE ON agent_memory, experiment_exposure, routing_decision,
                                agent_step, agent_run, audit_event TO {MAINTENANCE_ROLE};
        """
    )

    for table, columns in COLUMN_CLASSIFICATION.items():
        op.execute(
            "\n".join(
                f"COMMENT ON COLUMN {table}.{column} IS {_sql_literal(comment)};"
                for column, comment in columns.items()
            )
        )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE routing_decision, experiment_exposure, experiment,
                   agent_memory, agent_step, agent_run;
        ALTER TABLE tenant DROP COLUMN experiments_enabled;
        """
    )
