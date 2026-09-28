"""Separate editable library annotations from execution provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("artifacts", sa.Column("title", sa.String(200), nullable=False, server_default=""))
    op.add_column("artifacts", sa.Column("notes", sa.Text(), nullable=False, server_default=""))
    op.add_column("artifacts", sa.Column("library_updated_at", sa.DateTime(), nullable=True))
    op.add_column("artifacts", sa.Column("trashed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_artifacts_trashed_at", "artifacts", ["trashed_at"])


def downgrade():
    op.drop_index("ix_artifacts_trashed_at", table_name="artifacts")
    with op.batch_alter_table("artifacts") as batch:
        for name in ("trashed_at", "library_updated_at", "notes", "title"):
            batch.drop_column(name)
