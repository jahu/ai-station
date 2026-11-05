"""Allow distinct complete models to share one primary physical object."""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("model_definitions", sa.Column("binding_key", sa.String(64), nullable=True))
    op.drop_index("uq_model_definitions_file_id", table_name="model_definitions")
    op.create_index(
        "uq_model_definitions_file_default",
        "model_definitions",
        ["file_id"],
        unique=True,
        sqlite_where=sa.text("binding_key IS NULL"),
        postgresql_where=sa.text("binding_key IS NULL"),
    )
    op.create_index("uq_model_definitions_binding_key", "model_definitions", ["binding_key"], unique=True)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM model_definitions WHERE binding_key IS NOT NULL")):
        raise RuntimeError("Restore a reviewed backup rather than discard additional logical model bindings")
    op.drop_index("uq_model_definitions_binding_key", table_name="model_definitions")
    op.drop_index("uq_model_definitions_file_default", table_name="model_definitions")
    op.drop_column("model_definitions", "binding_key")
    op.create_index("uq_model_definitions_file_id", "model_definitions", ["file_id"], unique=True)
