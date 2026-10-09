"""Optional bounded registry tool calling during an agent report."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agents",
        sa.Column("tool_calling", sa.String(length=20), nullable=False, server_default="none"),
    )


def downgrade():
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("tool_calling")
