"""Account identities and revocable session storage; private data scoping follows."""

import re
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def _valid_legacy_password(value):
    if not isinstance(value, dict) or value.get("algorithm") != "pbkdf2-sha256":
        return False
    try:
        return (
            re.fullmatch(r"[0-9a-f]{64}", value.get("hash", "")) is not None
            and re.fullmatch(r"[0-9a-f]{32}", value.get("salt", "")) is not None
            and 100_000 <= int(value.get("iterations", 600_000)) <= 2_000_000
        )
    except (TypeError, ValueError):
        return False


def upgrade():
    users = op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("normalized_username", sa.String(128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("bootstrap_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("legacy_operator", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("password_record", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.Column("totp_secret_ref", sa.String(200), nullable=True),
        sa.Column("totp_enabled_at", sa.DateTime(), nullable=True),
        sa.Column("totp_last_step", sa.Integer(), nullable=True),
        sa.Column("recovery_code_hashes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("NOT bootstrap_pending OR (is_admin AND NOT enabled)", name="ck_user_bootstrap"),
    )
    sessions = op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lookup_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("token_record", sa.JSON(), nullable=False),
        sa.Column("label", sa.String(160), nullable=False, server_default=""),
        sa.Column("legacy_operator_key", sa.String(200), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("mfa_verified_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table(
        "user_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "key", name="uq_user_setting"),
    )
    op.create_index("ix_user_settings_user_id", "user_settings", ["user_id"])
    op.create_table(
        "account_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "subject_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name in ["actor_user_id", "subject_user_id", "action", "created_at"]:
        op.create_index("ix_account_events_" + name, "account_events", [name])

    connection = op.get_bind()
    settings = sa.table("settings", sa.column("key", sa.String()), sa.column("value", sa.JSON()))
    old = connection.execute(sa.select(settings.c.value).where(settings.c.key == "operator_auth")).first()
    raw = old[0] if old is not None and isinstance(old[0], dict) else {}
    credential = {key: raw[key] for key in ("algorithm", "salt", "hash", "iterations") if key in raw}
    valid = _valid_legacy_password(credential)
    owner = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # An existing malformed credential must never become an open bootstrap claim.
    # Preserve it and require explicit local recovery instead of replacing it.
    connection.execute(
        users.insert().values(
            id=owner,
            username="admin",
            normalized_username="admin",
            display_name="Station owner",
            is_admin=True,
            enabled=valid,
            bootstrap_pending=old is None,
            legacy_operator=old is not None,
            password_record=credential,
            created_at=now,
            updated_at=now,
        )
    )
    if valid:
        old_sessions = connection.execute(
            sa.select(settings.c.key, settings.c.value).where(
                sa.or_(
                    settings.c.key == "operator_session",
                    settings.c.key.startswith("operator_session:", autoescape=True),
                )
            )
        )
        for key, value in old_sessions:
            if not isinstance(value, dict) or not value.get("token_hash") or not value.get("salt"):
                continue
            lookup = key.partition(":")[2] if key != "operator_session" else None
            if lookup is not None and re.fullmatch(r"[0-9a-f]{64}", lookup) is None:
                continue
            connection.execute(
                sessions.insert().values(
                    id=str(uuid.uuid4()),
                    user_id=owner,
                    lookup_hash=lookup,
                    token_record={
                        name: value[name]
                        for name in (
                            "token_hash",
                            "salt",
                            "issued_at",
                            "last_seen_at",
                            "expires_at",
                            "idle_timeout_seconds",
                        )
                        if name in value
                    },
                    legacy_operator_key=key,
                    label="Migrated operator session",
                    created_at=now,
                )
            )
    # Keep legacy credential/session rows until the complete account cutover.
    # This schema alone exposes no additional account or private-data API.


def downgrade():
    connection = op.get_bind()
    used = connection.execute(
        sa.text("SELECT count(*) FROM users WHERE NOT legacy_operator AND NOT bootstrap_pending")
    ).scalar_one()
    used += connection.execute(sa.text("SELECT count(*) FROM user_settings")).scalar_one()
    used += connection.execute(sa.text("SELECT count(*) FROM account_events")).scalar_one()
    if used:
        raise RuntimeError(
            "Accounts have been used; restore a reviewed stopped-service backup instead of dropping them"
        )
    op.drop_table("account_events")
    op.drop_table("user_settings")
    op.drop_table("user_sessions")
    op.drop_table("users")
