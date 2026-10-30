"""Preserved creative projects with immutable private timeline revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def change(values):
    db = op.get_bind()
    sqlite = db.dialect.name == "sqlite"
    if sqlite:
        # Supplied recovery/test connections may still use sqlite3 legacy DDL
        # autocommit. Deferral must live inside the actual rebuild transaction.
        if not db.connection.driver_connection.in_transaction:
            db.exec_driver_sql("BEGIN IMMEDIATE")
        if db.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Repair existing foreign keys before migrating creative history")
        db.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    with op.batch_alter_table("creative_sessions") as batch:
        batch.drop_constraint("ck_creative_capability", type_="check")
        batch.create_check_constraint(
            "ck_creative_capability", "capability IN (" + ",".join("'" + v + "'" for v in values) + ")"
        )
    if sqlite:
        # Rebuilding this parent table preserves every referenced identity. SQLite
        # retains deferred DROP bookkeeping even after recreation; check actual
        # relationships before clearing that bookkeeping, with enforcement ON.
        if db.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Creative history foreign keys changed during migration")
        db.exec_driver_sql("PRAGMA defer_foreign_keys=OFF")


def upgrade():
    change(["images", "video", "music", "speech", "avatars", "effects", "timeline"])
    op.create_table(
        "timeline_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("creative_sessions.id"), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), sa.ForeignKey("timeline_revisions.id"), nullable=True),
        sa.Column("client_request_id", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "client_request_id", name="uq_timeline_revision_receipt"),
        sa.UniqueConstraint("session_id", "position", name="uq_timeline_revision_position"),
        sa.CheckConstraint("position > 0", name="ck_timeline_revision_position"),
    )
    op.create_index("ix_timeline_revisions_session_id", "timeline_revisions", ["session_id"])


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM creative_sessions WHERE capability='timeline'")
    ) or op.get_bind().scalar(sa.text("SELECT count(*) FROM timeline_revisions")):
        raise RuntimeError("Keep timeline history; restore a reviewed backup instead")
    op.drop_table("timeline_revisions")
    change(["images", "video", "music", "speech", "avatars", "effects"])
