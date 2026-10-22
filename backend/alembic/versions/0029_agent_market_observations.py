"""Reviewed market scopes, source quotes and durable threshold-alert receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("market", sa.JSON(), nullable=True))
    op.create_table(
        "market_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("policy_key", sa.String(64), nullable=False),
        sa.Column("instrument", sa.String(16), nullable=False),
        sa.Column("trade_id", sa.String(32), nullable=False),
        sa.Column("price", sa.String(48), nullable=False),
        sa.Column("source_at", sa.DateTime(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source_url", sa.String(200), nullable=False),
        sa.UniqueConstraint("agent_id", "policy_key", "instrument", "trade_id", name="uq_market_trade"),
    )
    op.create_index("ix_market_agent_policy", "market_observations", ["agent_id", "policy_key"])
    op.create_table(
        "market_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "observation_id",
            sa.String(36),
            sa.ForeignKey("market_observations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("baseline_id", sa.String(36), sa.ForeignKey("market_observations.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("change_percent", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("notice_id", sa.String(36), sa.ForeignKey("notices.id"), nullable=True, unique=True),
    )


def downgrade():
    op.drop_table("market_alerts")
    op.drop_index("ix_market_agent_policy", table_name="market_observations")
    op.drop_table("market_observations")
    op.drop_column("agents", "market")
