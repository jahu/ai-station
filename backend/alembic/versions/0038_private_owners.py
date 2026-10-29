"""Private root ownership without rebuilding populated SQLite parent tables."""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

ROOTS = (
    "tasks",
    "runs",
    "artifacts",
    "conversations",
    "projects",
    "agents",
    "approvals",
    "memories",
    "connectors",
    "chat_providers",
)


def upgrade():
    connection = op.get_bind()
    owners = connection.execute(sa.text("SELECT id FROM users ORDER BY created_at, id")).scalars().all()
    if len(owners) != 1:
        raise RuntimeError(
            "Assign private data owners explicitly before migrating an existing multi-user database"
        )
    owner = owners[0]
    for name in ROOTS:
        # SQLite supports an inline nullable REFERENCES column. Avoid a batch
        # rebuild that could cascade or disrupt populated child/FTS tables.
        if connection.dialect.name == "sqlite":
            # Alembic emits a separate ADD CONSTRAINT for ForeignKey columns,
            # which SQLite cannot support. These identifiers are fixed above.
            op.execute(f'ALTER TABLE "{name}" ADD COLUMN owner_id VARCHAR(36) REFERENCES users (id)')
        else:
            op.add_column(
                name, sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True)
            )
        op.create_index(f"ix_{name}_owner_id", name, ["owner_id"])
        table = sa.table(name, sa.column("owner_id", sa.String(36)))
        connection.execute(table.update().values(owner_id=owner))

    # Personal provider/connector names must be reusable by different accounts.
    # These two legacy constraints are the only required table rebuilds. SQLite
    # SET NULL on the existing email FK is restored by exact ID in this same
    # transaction; private roots/children otherwise retain their original tables.
    deliveries = connection.execute(
        sa.text("SELECT id, connector_id FROM email_deliveries WHERE connector_id IS NOT NULL")
    ).all()
    convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    for name, constraint in (
        ("connectors", "uq_connector_owner_key"),
        ("chat_providers", "uq_chat_provider_owner_key"),
    ):
        with op.batch_alter_table(name, naming_convention=convention) as batch:
            batch.drop_constraint(f"uq_{name}_key", type_="unique")
            batch.create_unique_constraint(constraint, ["owner_id", "key"])
    for identity, connector_id in deliveries:
        connection.execute(
            sa.text("UPDATE email_deliveries SET connector_id=:connector WHERE id=:id"),
            {"connector": connector_id, "id": identity},
        )


def downgrade():
    connection = op.get_bind()
    occupied = any(
        connection.execute(sa.text(f'SELECT count(*) FROM "{name}"')).scalar_one() for name in ROOTS
    )
    used = connection.execute(sa.text("SELECT count(*) FROM users WHERE NOT bootstrap_pending")).scalar_one()
    if occupied or used:
        raise RuntimeError("Private ownership cannot be discarded; restore a reviewed stopped-service backup")
    convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    for name, constraint in (
        ("connectors", "uq_connector_owner_key"),
        ("chat_providers", "uq_chat_provider_owner_key"),
    ):
        with op.batch_alter_table(name, naming_convention=convention) as batch:
            batch.drop_constraint(constraint, type_="unique")
            batch.create_unique_constraint(f"uq_{name}_key", ["key"])
            batch.drop_index(f"ix_{name}_owner_id")
            batch.drop_column("owner_id")
    for name in reversed(ROOTS):
        if name in {"connectors", "chat_providers"}:
            continue
        op.drop_index(f"ix_{name}_owner_id", table_name=name)
        op.drop_column(name, "owner_id")
