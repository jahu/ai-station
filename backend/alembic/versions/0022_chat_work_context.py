"""Explicit conversation selection of an existing coding Task."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_work_contexts",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("chat_work_contexts")
