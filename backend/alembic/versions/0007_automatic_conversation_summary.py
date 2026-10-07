"""Persist opt-in automatic conversation context maintenance."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversations", sa.Column("auto_summary", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade():
    # Native DROP COLUMN preserves the parent table and its referenced rows.
    op.drop_column("conversations", "auto_summary")
