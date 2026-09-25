"""Persist model discovery observations without changing external model files."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("model_files", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.add_column("model_files", sa.Column("last_scan_run_id", sa.String(36), nullable=True))
    op.add_column(
        "model_files", sa.Column("availability", sa.String(20), nullable=False, server_default="unknown")
    )


def downgrade():
    op.drop_column("model_files", "availability")
    op.drop_column("model_files", "last_scan_run_id")
    op.drop_column("model_files", "last_seen_at")
