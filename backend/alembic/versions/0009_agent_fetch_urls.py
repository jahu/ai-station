"""Persist reviewed public URLs for agent HTTP fetch."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("fetch_urls", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("fetch_urls")
