"""Explicit opt-in automatic project dependency and validation policies."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects",
        sa.Column("auto_install_dependencies", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "projects", sa.Column("auto_validate", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade():
    op.drop_column("projects", "auto_validate")
    op.drop_column("projects", "auto_install_dependencies")
