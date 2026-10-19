"""Knowledge service: spaces, documents, versions, chunks; intent on routing decisions.

ADR-015 (knowledge and intent router), ADR-004 (FTS + pgvector in Postgres), ADR-003 (RLS).
Access is decided by the database before retrieval: tenant or public visibility, AND the
caller's role in the space's allowed_roles. Chunks carry a copy of the ACL so the policy
needs no join; changing a space's ACL updates its documents and chunks in one transaction.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLE = "secondchance_app"
MAINTENANCE_ROLE = "secondchance_maintenance"
ROLES = "ARRAY['donor', 'coordinator', 'volunteer', 'center_staff', 'org_admin', 'platform_admin']::text[]"
# Admins of the owning network always see its spaces; 'system' is the ingestion worker.
READ_ACL = (
    "(tenant_id = current_tenant_id() OR visibility = 'public')"
    " AND (current_setting('app.role', true) = ANY(allowed_roles)"
    "      OR (tenant_id = current_tenant_id()"
    "          AND current_setting('app.role', true) IN ('org_admin', 'platform_admin', 'system')))"
)

N, P = "pii:none", "pii:personal"
COMMENTS = {
    "knowledge_space": {
        "id": f"{N}; space identifier", "tenant_id": f"{N}; owning network (RLS)", "name": f"{N}; space name",
        "kind": f"{N}; public, ngo_private, territorial, donor or shared", "visibility": f"{N}; public or tenant",
        "allowed_roles": f"{N}; roles that may read (ACL)", "territory": f"{N}; relevance filter, never authorization",
        "created_at": f"{N}; creation time",
    },
    "document": {
        "id": f"{N}; document identifier", "tenant_id": f"{N}; owning network (RLS)", "space_id": f"{N}; knowledge space",
        "title": f"{N}; document title", "language": f"{N}; it, en or da", "document_type": f"{N}; guideline, regulation, manual",
        "territory": f"{N}; relevance filter", "source_uri": f"{N}; provenance of the original",
        "visibility": f"{N}; ACL copied from the space", "allowed_roles": f"{N}; ACL copied from the space",
        "active_version": f"{N}; version served by retrieval", "created_by": f"{P}; OIDC subject pseudonym of the uploader",
        "created_at": f"{N}; creation time", "deleted_at": f"{N}; soft delete, excluded from retrieval at once",
    },
    "document_version": {
        "id": f"{N}; version identifier and ingestion job id", "tenant_id": f"{N}; owning network (RLS)",
        "document_id": f"{N}; document", "version": f"{N}; version number", "content_sha256": f"{N}; checksum of the original",
        "pipeline_version": f"{N}; ingestion pipeline that produced the chunks", "object_key": f"{N}; original in object storage",
        "size_bytes": f"{N}; original size", "page_count": f"{N}; pages", "status": f"{N}; ingestion state",
        "error_category": f"{N}; failure category, never a message", "quality": f"{N}; quality gate metrics",
        "lease_until": f"{N}; worker claim expiry", "created_at": f"{N}; upload time", "published_at": f"{N}; publication time",
    },
    "knowledge_chunk": {
        "id": f"{N}; chunk identifier", "tenant_id": f"{N}; owning network (RLS)", "document_id": f"{N}; document",
        "version_id": f"{N}; document version", "space_id": f"{N}; knowledge space", "visibility": f"{N}; ACL copy",
        "allowed_roles": f"{N}; ACL copy", "active": f"{N}; true only for the published version",
        "language": f"{N}; chunk language", "section_path": f"{N}; headings from the document root",
        "page_start": f"{N}; first page", "page_end": f"{N}; last page", "ordinal": f"{N}; position in the document",
        "content": f"{P}; document text, may mention people (authorised documents only)",
        "tsv": f"{N}; full-text index", "embedding": f"{P}; vector derived from content",
        "embedding_model": f"{N}; model that produced the vector", "created_at": f"{N}; creation time",
    },
    "routing_decision": {"intent": f"{N}; intent class (ADR-015)"},
}


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION fts_config(lang text) RETURNS regconfig LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE lang WHEN 'it' THEN 'pg_catalog.italian'::regconfig
                             WHEN 'da' THEN 'pg_catalog.danish'::regconfig
                             ELSE 'pg_catalog.english'::regconfig END
        $$;

        CREATE TABLE knowledge_space (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     uuid NOT NULL DEFAULT current_tenant_id() REFERENCES tenant (id),
            name          text NOT NULL CHECK (length(name) BETWEEN 2 AND 120),
            kind          text NOT NULL CHECK (kind IN ('public', 'ngo_private', 'territorial', 'donor', 'shared')),
            visibility    text NOT NULL CHECK (visibility IN ('public', 'tenant')),
            allowed_roles text[] NOT NULL CHECK (cardinality(allowed_roles) > 0 AND allowed_roles <@ {ROLES}),
            territory     text,
            created_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            CHECK ((visibility = 'public') = (kind = 'public'))
        );

        CREATE TABLE document (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL DEFAULT current_tenant_id(),
            space_id       uuid NOT NULL,
            title          text NOT NULL CHECK (length(title) BETWEEN 2 AND 200),
            language       text NOT NULL CHECK (language IN ('it', 'en', 'da')),
            document_type  text NOT NULL CHECK (document_type IN ('guideline', 'regulation', 'manual', 'procedure', 'other')),
            territory      text,
            source_uri     text,
            visibility     text NOT NULL CHECK (visibility IN ('public', 'tenant')),
            allowed_roles  text[] NOT NULL,
            active_version integer,
            created_by     text NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            deleted_at     timestamptz,
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, space_id) REFERENCES knowledge_space (tenant_id, id)
        );

        -- One row per uploaded version; it is also the ingestion job (GET /ingestion/jobs/{{id}}).
        CREATE TABLE document_version (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        uuid NOT NULL DEFAULT current_tenant_id(),
            document_id      uuid NOT NULL,
            version          integer NOT NULL CHECK (version >= 1),
            content_sha256   text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
            pipeline_version text NOT NULL,
            object_key       text NOT NULL,
            size_bytes       integer NOT NULL CHECK (size_bytes > 0),
            page_count       integer NOT NULL CHECK (page_count > 0),
            status           text NOT NULL DEFAULT 'uploaded' CHECK (status IN (
                                 'uploaded', 'processing', 'published', 'failed', 'superseded')),
            error_category   text,
            quality          jsonb NOT NULL DEFAULT '{{}}',
            lease_until      timestamptz,
            created_at       timestamptz NOT NULL DEFAULT now(),
            published_at     timestamptz,
            UNIQUE (document_id, version),
            -- Idempotency: the same bytes through the same pipeline are ingested once.
            UNIQUE (document_id, content_sha256, pipeline_version),
            FOREIGN KEY (tenant_id, document_id) REFERENCES document (tenant_id, id)
        );

        CREATE TABLE knowledge_chunk (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid NOT NULL DEFAULT current_tenant_id(),
            document_id     uuid NOT NULL,
            version_id      uuid NOT NULL REFERENCES document_version (id),
            space_id        uuid NOT NULL,
            visibility      text NOT NULL CHECK (visibility IN ('public', 'tenant')),
            allowed_roles   text[] NOT NULL,
            active          boolean NOT NULL DEFAULT false,
            language        text NOT NULL CHECK (language IN ('it', 'en', 'da')),
            section_path    text[] NOT NULL DEFAULT '{{}}',
            page_start      integer NOT NULL CHECK (page_start >= 1),
            page_end        integer NOT NULL CHECK (page_end >= page_start),
            ordinal         integer NOT NULL CHECK (ordinal >= 0),
            content         text NOT NULL CHECK (length(content) BETWEEN 1 AND 12000),
            tsv             tsvector GENERATED ALWAYS AS (to_tsvector(fts_config(language), content)) STORED,
            embedding       vector(1024),
            embedding_model text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            CHECK ((embedding IS NULL) = (embedding_model IS NULL)),
            FOREIGN KEY (tenant_id, document_id) REFERENCES document (tenant_id, id)
        );
        CREATE INDEX knowledge_chunk_tsv ON knowledge_chunk USING gin (tsv) WHERE active;
        CREATE INDEX knowledge_chunk_embedding ON knowledge_chunk USING hnsw (embedding vector_cosine_ops) WHERE active;
        CREATE INDEX knowledge_chunk_version ON knowledge_chunk (version_id);
        CREATE INDEX knowledge_chunk_scope ON knowledge_chunk (tenant_id, space_id) WHERE active;

        ALTER TABLE routing_decision ADD COLUMN intent text CHECK (intent IN (
            'KNOWLEDGE_QUERY', 'DIRECT_OPERATION', 'SINGLE_CAPABILITY', 'MULTI_AGENT_TASK',
            'CLARIFICATION', 'UNSUPPORTED'));
        """
    )
    for table in ("knowledge_space", "document", "knowledge_chunk"):
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            CREATE POLICY acl_read ON {table} FOR SELECT USING ({READ_ACL});
            CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK (tenant_id = current_tenant_id());
            CREATE POLICY tenant_update ON {table} FOR UPDATE
                USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
            """
        )
    op.execute(
        f"""
        ALTER TABLE document_version ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON document_version
            USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

        GRANT SELECT, INSERT, UPDATE ON knowledge_space, document, document_version, knowledge_chunk TO {APP_ROLE};
        GRANT SELECT, DELETE ON knowledge_chunk, document_version, document TO {MAINTENANCE_ROLE};
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
        ALTER TABLE routing_decision DROP COLUMN intent;
        DROP TABLE knowledge_chunk, document_version, document, knowledge_space;
        DROP FUNCTION fts_config(text);
        """
    )
