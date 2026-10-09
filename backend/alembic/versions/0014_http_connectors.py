"""Named HTTP connectors: kind, enablement and last health Run."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "connectors",
        sa.Column("kind", sa.String(length=80), nullable=False, server_default="http"),
    )
    op.add_column(
        "connectors",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.add_column(
        "connectors",
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.add_column(
        "connectors",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.add_column("connectors", sa.Column("last_run_id", sa.String(length=36), nullable=True))


def downgrade():
    with op.batch_alter_table("connectors") as batch:
        batch.drop_column("last_run_id")
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("enabled")
        batch.drop_column("kind")
