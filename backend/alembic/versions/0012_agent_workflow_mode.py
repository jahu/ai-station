"""Persist sequential or gated agent workflow execution."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agents",
        sa.Column("workflow_mode", sa.String(length=20), nullable=False, server_default="sequential"),
    )


def downgrade():
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("workflow_mode")
