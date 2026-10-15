"""Explicit frozen component/development validation configuration."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("validation_environment", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("projects", "validation_environment")
