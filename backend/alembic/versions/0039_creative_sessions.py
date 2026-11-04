"""Private durable creative sessions and append-only generation turns."""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "creative_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("capability", sa.String(20), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "capability IN ('images','video','music','speech','avatars')", name="ck_creative_capability"
        ),
    )
    for name in ("owner_id", "capability"):
        op.create_index("ix_creative_sessions_" + name, "creative_sessions", [name])
    op.create_table(
        "creative_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("creative_sessions.id"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False, unique=True),
        sa.Column("parent_turn_id", sa.String(36), sa.ForeignKey("creative_turns.id"), nullable=True),
        sa.Column("client_request_id", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column("request_parameters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "client_request_id", name="uq_creative_turn_receipt"),
        sa.UniqueConstraint("session_id", "position", name="uq_creative_turn_position"),
        sa.CheckConstraint("position > 0", name="ck_creative_turn_position"),
    )
    for name in ("session_id", "task_id"):
        op.create_index("ix_creative_turns_" + name, "creative_turns", [name])


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT count(*) FROM creative_sessions")):
        raise RuntimeError("Creative history cannot be discarded; restore a reviewed backup")
    op.drop_table("creative_turns")
    op.drop_table("creative_sessions")
