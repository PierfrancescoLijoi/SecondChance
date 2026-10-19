"""Polish as a fourth document language.

PostgreSQL ships no Polish stemmer, so Polish text is indexed with the 'simple' configuration
(lower-cased words, no stemming). Dense retrieval covers inflected forms; a Polish ispell
dictionary can replace 'simple' later without touching the callers.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _fts_config(languages: dict[str, str]) -> str:
    cases = "\n".join(f"WHEN '{code}' THEN 'pg_catalog.{config}'::regconfig" for code, config in languages.items())
    return f"""
        CREATE OR REPLACE FUNCTION fts_config(lang text) RETURNS regconfig LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE lang {cases} ELSE 'pg_catalog.english'::regconfig END
        $$;
    """


def _languages(codes: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{code}'" for code in codes)
    return "\n".join(
        f"ALTER TABLE {table} DROP CONSTRAINT {table}_language_check,"
        f" ADD CONSTRAINT {table}_language_check CHECK (language IN ({allowed}));"
        for table in ("document", "knowledge_chunk")
    )


def upgrade() -> None:
    op.execute(_fts_config({"it": "italian", "da": "danish", "pl": "simple"}))
    op.execute(_languages(("it", "en", "da", "pl")))
    op.execute("COMMENT ON COLUMN document.language IS 'pii:none; it, en, da or pl'")


def downgrade() -> None:
    # Polish documents cannot exist in the older schema: they go, with their versions and chunks.
    op.execute("""
        DELETE FROM knowledge_chunk WHERE language = 'pl' OR document_id IN (SELECT id FROM document WHERE language = 'pl');
        DELETE FROM document_version WHERE document_id IN (SELECT id FROM document WHERE language = 'pl');
        DELETE FROM document WHERE language = 'pl';
    """)
    op.execute(_languages(("it", "en", "da")))
    op.execute(_fts_config({"it": "italian", "da": "danish"}))
    op.execute("COMMENT ON COLUMN document.language IS 'pii:none; it, en or da'")
