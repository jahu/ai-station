"""Partial coverage offset for oversized conversation-summary messages."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversation_summaries",
        sa.Column("covered_offset", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    with op.batch_alter_table("conversation_summaries") as batch:
        batch.drop_column("covered_offset")
