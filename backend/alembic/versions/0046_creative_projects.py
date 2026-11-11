"""Private creative identities and optional workspace membership; preserve history."""

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def membership(add):
    db = op.get_bind()
    sqlite = db.dialect.name == "sqlite"
    if sqlite:
        if not db.connection.driver_connection.in_transaction:
            db.exec_driver_sql("BEGIN IMMEDIATE")
        if db.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Repair foreign keys before changing creative workspaces")
        db.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    with op.batch_alter_table("creative_sessions") as batch:
        if add:
            batch.add_column(sa.Column("creative_project_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_creative_session_project", "creative_projects", ["creative_project_id"], ["id"]
            )
            batch.create_index("ix_creative_sessions_creative_project_id", ["creative_project_id"])
        else:
            batch.drop_index("ix_creative_sessions_creative_project_id")
            batch.drop_constraint("fk_creative_session_project", type_="foreignkey")
            batch.drop_column("creative_project_id")
    if sqlite:
        if db.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Creative history relationships changed during migration")
        db.exec_driver_sql("PRAGMA defer_foreign_keys=OFF")


def upgrade():
    op.create_table(
        "creative_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("identity", sa.JSON(), nullable=False),
        sa.Column("defaults", sa.JSON(), nullable=False),
        sa.Column("logo_artifact_id", sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_creative_projects_owner_id", "creative_projects", ["owner_id"])
    membership(True)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM creative_projects")):
        raise RuntimeError("Restore a reviewed backup rather than discard creative identities")
    membership(False)
    op.drop_index("ix_creative_projects_owner_id", "creative_projects")
    op.drop_table("creative_projects")
