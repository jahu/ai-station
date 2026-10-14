"""Durable idempotent stage identity for segmented media on existing Runs."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("operation_key", sa.String(160), nullable=True))
    op.create_index("uq_run_task_operation", "runs", ["task_id", "operation_key"], unique=True)


def downgrade():
    op.drop_index("uq_run_task_operation", table_name="runs")
    op.drop_column("runs", "operation_key")
