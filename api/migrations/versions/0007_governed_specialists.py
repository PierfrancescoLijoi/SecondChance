"""Allow governed specialist names in durable agent steps.

Specialists are still allow-listed by the application catalog. The database enforces the
same safe identifier shape so adding a specialist does not require a schema migration.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_step DROP CONSTRAINT agent_step_agent_check, "
        "ADD CONSTRAINT agent_step_agent_check CHECK (agent ~ '^[a-z][a-z0-9_]{2,48}$')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_step WHERE agent NOT IN ('supervisor', 'intake', 'knowledge', 'matching', 'compliance')")
    op.execute(
        "ALTER TABLE agent_step DROP CONSTRAINT agent_step_agent_check, "
        "ADD CONSTRAINT agent_step_agent_check CHECK (agent IN "
        "('supervisor', 'intake', 'knowledge', 'matching', 'compliance'))"
    )
