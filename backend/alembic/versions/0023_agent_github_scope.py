"""Persist an agent's explicitly reviewed GitHub repository scope."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("github", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("agents", "github")
