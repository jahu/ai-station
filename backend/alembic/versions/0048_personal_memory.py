"""Account-controlled personal learning metadata; existing memories are preserved."""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversations", sa.Column("personal_memory", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "memories", sa.Column("learning", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
    )


def downgrade():
    op.drop_column("memories", "learning")
    op.drop_column("conversations", "personal_memory")
