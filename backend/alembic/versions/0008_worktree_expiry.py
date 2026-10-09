"""Automatic unused worktree expiry. Existing rows stay unscheduled."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("worktrees", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.create_index("ix_worktrees_expires_at", "worktrees", ["expires_at"])


def downgrade():
    op.drop_index("ix_worktrees_expires_at", table_name="worktrees")
    op.drop_column("worktrees", "expires_at")
