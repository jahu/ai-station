"""Atomic first-send receipts and optimistic conversation settings versions."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversations", sa.Column("settings_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "chat_turn_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("user_message_id", sa.String(36), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("chat_turn_requests")
    op.drop_column("conversations", "settings_version")
