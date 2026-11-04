"""Retain deleted registry definitions for historical provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("agents", "projects"):
        op.add_column(name, sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade():
    db = op.get_bind()
    for name in ("agents", "projects"):
        if db.scalar(sa.text(f"SELECT count(*) FROM {name} WHERE deleted_at IS NOT NULL")):
            raise RuntimeError("Restore a reviewed backup rather than resurrecting deleted definitions")
    for name in ("agents", "projects"):
        op.drop_column(name, "deleted_at")
