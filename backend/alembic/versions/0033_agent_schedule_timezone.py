"""Preserve UTC schedules while adding explicit IANA timezone selection."""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agents", sa.Column("schedule_timezone", sa.String(100), nullable=False, server_default="UTC")
    )


def downgrade():
    op.drop_column("agents", "schedule_timezone")
