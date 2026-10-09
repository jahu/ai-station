"""Optional durable approval before an agent Run executes."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agents",
        sa.Column("require_approval", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade():
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("require_approval")
