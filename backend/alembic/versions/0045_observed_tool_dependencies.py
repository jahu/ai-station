"""Durable controller dependencies may observe a terminal tool failure."""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "run_dependencies",
        sa.Column("require_success", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    bind = op.get_bind()
    if bind.scalar(
        sa.text("SELECT count(*) FROM run_dependencies WHERE require_success = false")
    ) or bind.scalar(sa.text("SELECT count(*) FROM runs WHERE status = 'waiting_for_tool'")):
        raise RuntimeError("Restore a reviewed backup rather than discard durable controller state")
    op.drop_column("run_dependencies", "require_success")
