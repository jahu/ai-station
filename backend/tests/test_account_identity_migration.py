"""Staged account storage only; these tests do not establish API isolation."""

import hashlib
import hmac
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from app.config import get_settings
from app.db import alembic_config, migrate, reset_engine, session_factory, utcnow
from app.models import Setting, Task, User, UserSession, UserSetting
from app.operator_auth import digest, session_verdict
from sqlalchemy.exc import IntegrityError


def legacy_database():
    reset_engine()
    command.downgrade(alembic_config(), "0036")


def credential():
    salt = b"0123456789abcdef"
    return {
        "algorithm": "pbkdf2-sha256",
        "salt": salt.hex(),
        "hash": digest("synthetic-owner-password", salt),
        "iterations": 600_000,
    }


def token_record(token, *, expired=False):
    salt = b"abcdefghijklmnop"
    now = utcnow()
    return {
        "salt": salt.hex(),
        "token_hash": hmac.new(salt, token.encode(), hashlib.sha256).hexdigest(),
        "issued_at": (now - timedelta(hours=13 if expired else 0)).isoformat(),
        "last_seen_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=-1 if expired else 12)).isoformat(),
        "idle_timeout_seconds": 1800,
    }


def test_fresh_install_has_only_a_disabled_bootstrap_owner_and_no_password():
    with session_factory()() as session:
        owner = session.query(User).one()
        assert owner.bootstrap_pending and owner.is_admin and not owner.enabled
        assert owner.password_record == {} and not owner.legacy_operator
        assert owner.totp_secret_ref is None and owner.recovery_code_hashes == []
        assert session.query(UserSession).count() == 0
        first = owner.id
    migrate()
    with session_factory()() as session:
        assert session.query(User).one().id == first


def test_legacy_password_sessions_and_data_survive_without_plaintext_or_session_renewal():
    legacy_database()
    secret = credential()
    tokens = {
        "operator_session": "synthetic-first-cookie",
        "operator_session:"
        + hashlib.sha256(b"synthetic-second-cookie").hexdigest(): "synthetic-second-cookie",
    }
    records = {key: token_record(token, expired=i == 1) for i, (key, token) in enumerate(tokens.items())}
    with session_factory()() as session:
        session.add(Setting(key="operator_auth", value=secret))
        session.add_all(Setting(key=key, value=value) for key, value in records.items())
        task = Task(title="Legacy task", prompt="Synthetic private prompt")
        session.add(task)
        session.commit()
        task_id = task.id
    file = get_settings().data_dir / "artifacts" / "legacy-fixture.txt"
    file.write_text("Synthetic bytes remain unchanged")
    migrate()
    migrate()
    with session_factory()() as session:
        owner = session.query(User).one()
        assert owner.enabled and owner.is_admin and owner.legacy_operator and not owner.bootstrap_pending
        assert owner.password_record == secret and session.get(Setting, "operator_auth").value == secret
        assert session.get(Task, task_id).prompt == "Synthetic private prompt"
        sessions = session.query(UserSession).all()
        assert len(sessions) == 2 and all(row.user_id == owner.id for row in sessions)
        for row in sessions:
            assert row.token_record == records[row.legacy_operator_key]
            expected = "expired" if row.legacy_operator_key != "operator_session" else "valid"
            assert session_verdict(row.token_record, tokens[row.legacy_operator_key]) == expected
            assert tokens[row.legacy_operator_key] not in json.dumps(row.token_record)
            assert row.lookup_hash == (
                None
                if row.legacy_operator_key == "operator_session"
                else row.legacy_operator_key.partition(":")[2]
            )
    assert file.read_text() == "Synthetic bytes remain unchanged"


@pytest.mark.parametrize(
    "broken", [{}, {"algorithm": "pbkdf2-sha256", "hash": "invalid", "salt": "00"}, "invalid"]
)
def test_existing_broken_credentials_never_open_public_admin_bootstrap(broken):
    legacy_database()
    with session_factory()() as session:
        session.add(Setting(key="operator_auth", value=broken))
        session.commit()
    migrate()
    with session_factory()() as session:
        owner = session.query(User).one()
        assert owner.is_admin and owner.legacy_operator and not owner.enabled and not owner.bootstrap_pending
        assert session.get(Setting, "operator_auth").value == broken


def test_legacy_session_prefix_is_literal_and_unknown_secret_fields_are_not_imported():
    legacy_database()
    secret = credential()
    with session_factory()() as session:
        session.add(Setting(key="operator_auth", value={**secret, "unexpected_secret": "not imported"}))
        session.add(
            Setting(
                key="operator_session",
                value={**token_record("synthetic-cookie"), "unexpected_secret": "not imported"},
            )
        )
        session.add(Setting(key="operatorXsession:" + "a" * 64, value=token_record("other")))
        session.add(Setting(key="operator_session:malformed", value=token_record("bad-key")))
        session.commit()
    migrate()
    with session_factory()() as session:
        assert session.query(User).one().password_record == secret
        row = session.query(UserSession).one()
        assert row.legacy_operator_key == "operator_session"
        assert "unexpected_secret" not in row.token_record


def test_personal_setting_keys_are_namespaced_by_user_and_duplicate_names_are_rejected():
    with session_factory()() as session:
        users = [User(username=name, normalized_username=name.lower()) for name in ["Alice", "Bob"]]
        session.add_all(users)
        session.flush()
        session.add_all(
            UserSetting(user_id=user.id, key="editor", value={"label": user.username}) for user in users
        )
        session.commit()
        assert session.query(UserSetting).count() == 2
        session.add(User(username="ALICE", normalized_username="alice"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(UserSetting(user_id=users[0].id, key="editor", value={}))
        with pytest.raises(IntegrityError):
            session.commit()


def test_account_storage_cannot_be_dropped_after_use():
    with session_factory()() as session:
        session.add(User(id=str(uuid4()), username="Alice", normalized_username="alice"))
        session.commit()
    reset_engine()
    with pytest.raises(RuntimeError, match="Accounts have been used"):
        command.downgrade(alembic_config(), "0036")
    with session_factory()() as session:
        assert session.query(User).count() == 2
