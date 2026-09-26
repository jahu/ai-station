"""Inspectable incremental summaries linked to scoped memory and source Runs."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False, unique=True),
        sa.Column(
            "memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("covered_message_id", sa.String(36), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("covered_created_at", sa.DateTime(), nullable=False),
        sa.Column("source_message_ids", sa.JSON(), nullable=False),
        sa.Column("previous_summary_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_conversation_summaries_conversation_id", "conversation_summaries", ["conversation_id"]
    )


def downgrade():
    op.drop_table("conversation_summaries")
