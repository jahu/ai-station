"""Persist explicitly reviewed artifact scope for local Python agents."""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("data", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("agents", "data")
