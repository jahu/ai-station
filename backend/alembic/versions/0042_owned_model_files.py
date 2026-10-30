"""Portable app-owned model coordinates, preserving all discovered host files."""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def _begin():
    db = op.get_bind()
    if db.dialect.name == "sqlite":
        if not db.connection.driver_connection.in_transaction:
            db.exec_driver_sql("BEGIN IMMEDIATE")
        if db.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Repair existing model references before migration")
        db.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    return db


def _finish(db):
    if db.dialect.name == "sqlite":
        if db.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Model references changed during migration")
        db.exec_driver_sql("PRAGMA defer_foreign_keys=OFF")


def upgrade():
    db = _begin()
    with op.batch_alter_table("model_files") as batch:
        batch.alter_column("host_path", existing_type=sa.String(1200), nullable=True)
        batch.add_column(sa.Column("relative_path", sa.String(1200), nullable=True))
        batch.add_column(sa.Column("sha256", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_model_files_relative_path", ["relative_path"])
        batch.create_check_constraint(
            "ck_model_file_location",
            "(host_path IS NOT NULL AND relative_path IS NULL) OR "
            "(host_path IS NULL AND relative_path IS NOT NULL AND sha256 IS NOT NULL)",
        )
    _finish(db)


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT count(*) FROM model_files WHERE relative_path IS NOT NULL")):
        raise RuntimeError("Keep installed model identities; restore a reviewed backup instead")
    db = _begin()
    with op.batch_alter_table("model_files") as batch:
        batch.drop_constraint("ck_model_file_location", type_="check")
        batch.drop_constraint("uq_model_files_relative_path", type_="unique")
        batch.drop_column("sha256")
        batch.drop_column("relative_path")
        batch.alter_column("host_path", existing_type=sa.String(1200), nullable=False)
    _finish(db)
