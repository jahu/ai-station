"""Optional memory embeddings with explicit local model setup."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_embeddings",
        sa.Column(
            "memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_memory_embeddings_model", "memory_embeddings", ["model"])


def downgrade():
    op.drop_table("memory_embeddings")
