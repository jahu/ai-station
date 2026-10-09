"""Persisted in-app notices for saved agent notification policies."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notices_agent_id", "notices", ["agent_id"])
    op.create_index("ix_notices_run_id", "notices", ["run_id"])
    op.create_index("ix_notices_kind", "notices", ["kind"])
    op.create_index("ix_notices_created_at", "notices", ["created_at"])
    op.create_index("ix_notices_read_at", "notices", ["read_at"])


def downgrade():
    op.drop_index("ix_notices_read_at", table_name="notices")
    op.drop_index("ix_notices_created_at", table_name="notices")
    op.drop_index("ix_notices_kind", table_name="notices")
    op.drop_index("ix_notices_run_id", table_name="notices")
    op.drop_index("ix_notices_agent_id", table_name="notices")
    op.drop_table("notices")
