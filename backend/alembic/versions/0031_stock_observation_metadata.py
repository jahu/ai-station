"""Preserve quote currency, provider-time meaning and observed market session."""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "market_observations",
        sa.Column("source_metadata", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("market_observations", "source_metadata")
