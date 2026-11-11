"""Private Studio materials and immutable editorial revisions; existing work is untouched."""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "studio_materials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("creative_project_id", sa.String(36), sa.ForeignKey("creative_projects.id"), nullable=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name in ("owner_id", "creative_project_id"):
        op.create_index("ix_studio_materials_" + name, "studio_materials", [name])
    op.create_table(
        "studio_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("material_id", sa.String(36), sa.ForeignKey("studio_materials.id"), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), sa.ForeignKey("studio_revisions.id"), nullable=True),
        sa.Column("source_run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=True, unique=True),
        sa.Column("client_request_id", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("storyboard", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("project_snapshot", sa.JSON(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("material_id", "client_request_id", name="uq_studio_revision_receipt"),
        sa.UniqueConstraint("material_id", "position", name="uq_studio_revision_position"),
        sa.CheckConstraint("position > 0", name="ck_studio_revision_position"),
    )
    op.create_index("ix_studio_revisions_material_id", "studio_revisions", ["material_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM studio_materials")):
        raise RuntimeError("Restore a reviewed backup rather than discard Studio materials")
    op.drop_index("ix_studio_revisions_material_id", "studio_revisions")
    op.drop_table("studio_revisions")
    op.drop_index("ix_studio_materials_creative_project_id", "studio_materials")
    op.drop_index("ix_studio_materials_owner_id", "studio_materials")
    op.drop_table("studio_materials")
