"""Reviewed saved HTTP scope; legacy agent definitions retain their identity."""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("http", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("agents", "http")
