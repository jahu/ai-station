"""Persist explicit agent web queries without sending private goals/history."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("search_query", sa.String(500), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("search_query")
