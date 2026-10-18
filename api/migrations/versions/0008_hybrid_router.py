"""Allow governed hybrid and Bedrock routing decisions.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE routing_decision DROP CONSTRAINT routing_decision_router_check, "
        "ADD CONSTRAINT routing_decision_router_check "
        "CHECK (router IN ('baseline', 'bedrock', 'hybrid', 'rizzo_flow'))"
    )


def downgrade() -> None:
    # Old application versions cannot interpret the richer decisions.
    op.execute("DELETE FROM routing_decision WHERE router IN ('bedrock', 'hybrid')")
    op.execute(
        "ALTER TABLE routing_decision DROP CONSTRAINT routing_decision_router_check, "
        "ADD CONSTRAINT routing_decision_router_check CHECK (router IN ('baseline', 'rizzo_flow'))"
    )
