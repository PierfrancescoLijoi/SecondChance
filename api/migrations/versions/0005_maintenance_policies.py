"""Maintenance role without BYPASSRLS: explicit cross-tenant policies instead (ADR-014, ADR-018).

Aurora's master user (rds_superuser) may not grant BYPASSRLS, and a role that bypasses
every policy is broader than retention, erasure and re-queue jobs need. These policies
apply TO secondchance_maintenance only, and only on the tables those jobs read or delete.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

MAINTENANCE_ROLE = "secondchance_maintenance"
TABLES = (
    "agent_memory", "experiment_exposure", "routing_decision", "agent_step", "agent_run", "audit_event",
    "document_version", "knowledge_chunk", "document",
)


def upgrade() -> None:
    op.execute(
        "\n".join(
            f"CREATE POLICY maintenance_jobs ON {table} FOR ALL TO {MAINTENANCE_ROLE} USING (true);"
            for table in TABLES
        )
    )


def downgrade() -> None:
    op.execute("\n".join(f"DROP POLICY maintenance_jobs ON {table};" for table in TABLES))
