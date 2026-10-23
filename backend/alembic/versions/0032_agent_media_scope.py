"""Store explicitly reviewed optional agent media settings."""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("media", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("agents", "media")
