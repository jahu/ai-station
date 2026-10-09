"""Curated model definitions with load presets and install verification."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "model_definitions", sa.Column("status", sa.String(20), nullable=False, server_default="unverified")
    )
    op.add_column("model_definitions", sa.Column("last_verify_run_id", sa.String(36), nullable=True))
    op.add_column(
        "model_definitions",
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.add_column(
        "model_definitions",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_model_definitions_status", "model_definitions", ["status"])
    op.create_index("uq_model_definitions_file_id", "model_definitions", ["file_id"], unique=True)


def downgrade():
    op.drop_index("uq_model_definitions_file_id", table_name="model_definitions")
    op.drop_index("ix_model_definitions_status", table_name="model_definitions")
    op.drop_column("model_definitions", "updated_at")
    op.drop_column("model_definitions", "created_at")
    op.drop_column("model_definitions", "last_verify_run_id")
    op.drop_column("model_definitions", "status")
