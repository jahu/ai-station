"""Retain artifact provenance after explicitly approved permanent deletion."""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("artifacts", sa.Column("purged_at", sa.DateTime(), nullable=True))
    op.add_column("artifacts", sa.Column("purge_run_id", sa.String(36), nullable=True))


def downgrade():
    op.drop_column("artifacts", "purge_run_id")
    op.drop_column("artifacts", "purged_at")
