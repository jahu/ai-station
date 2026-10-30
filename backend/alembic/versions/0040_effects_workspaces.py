"""Preserve creative history while permitting synchronized sound workspaces."""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
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
    change(["images", "video", "music", "speech", "avatars", "effects"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM creative_sessions WHERE capability='effects'")):
        raise RuntimeError("Keep sound history; restore a reviewed backup instead")
    change(["images", "video", "music", "speech", "avatars"])
