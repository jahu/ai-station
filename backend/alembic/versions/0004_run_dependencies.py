"""Durable prerequisites for model and capability orchestration."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "run_dependencies",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("prerequisite_id", sa.String(36), sa.ForeignKey("runs.id"), primary_key=True),
        sa.CheckConstraint("run_id != prerequisite_id", name="no_self_dependency"),
    )
    op.create_index("ix_run_dependencies_prerequisite_id", "run_dependencies", ["prerequisite_id"])


def downgrade():
    op.drop_table("run_dependencies")
