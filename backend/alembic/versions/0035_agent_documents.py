"""Reviewed app-owned document scope; legacy definitions omit the absent field."""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("documents", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("agents", "documents")
