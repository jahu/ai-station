"""Persist reviewed email envelopes and conservative SMTP delivery receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connector_id", sa.String(36), sa.ForeignKey("connectors.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("message_id", sa.String(100), nullable=False, unique=True),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("accepted_recipients", sa.JSON(), nullable=False),
        sa.Column("refused_recipients", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("email_deliveries")
