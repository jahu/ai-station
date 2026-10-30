"""Restoring data never rolls account authority back to historical credentials."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pyotp
import pytest
from app import account_mfa, accounts
from app.account_credentials import password_matches
from app.config import get_settings
from app.db import control_session_factory
from app.models import Setting, Task, User, UserSession, UserSetting
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from station_recovery.storage import RecoveryError, current_security, normalize_copy

OLD = "synthetic previous account password"
NEW = "synthetic current account password"


@pytest.fixture
def private_backup():
    root = get_settings().data_dir
    with control_session_factory()() as session:
        owner = accounts.bootstrap_admin(session, "Owner", OLD, local_setup=True)
        device = accounts.login(session, "Owner", OLD)
        enrollment = account_mfa.begin_enrollment(session, device.principal, OLD)
        old_codes = account_mfa.confirm_enrollment(
            session, device.principal, OLD, pyotp.TOTP(enrollment.secret).now()
        )
        member = accounts.create_user(session, device.principal, "Member", OLD)
        member_device = accounts.login(session, "Member", OLD)
        task = Task(owner_id=owner.id, title="Private retained task")
        session.add(task)
        session.add(Setting(key="account_attempts:login", value={"synthetic_budget": "backup"}))
        session.add(
            UserSetting(
                user_id=owner.id,
                key="auth.abandoned_enrollment",
                value={"secret_ref": "synthetic-old-enrollment"},
            )
        )
        session.commit()
        owner_id, member_id, task_id = owner.id, member.id, task.id
    stage = root / "account-recovery-stage.sqlite"
    with (
        closing(sqlite3.connect(root / "db/ai-station.sqlite")) as source,
        closing(sqlite3.connect(stage)) as target,
    ):
        source.backup(target)
    with control_session_factory()() as session:
        accounts.change_password(session, device.principal, OLD, NEW)
        active = accounts.login(session, "Owner", NEW, second_factor=old_codes[0])
        fresh_codes = account_mfa.regenerate_recovery_codes(session, active.principal, NEW, old_codes[1])
        accounts.update_user(session, active.principal, member_id, enabled=False, is_admin=False)
        added = accounts.create_user(session, active.principal, "LaterUser", OLD)
        session.get(Setting, "account_attempts:login").value = {"synthetic_budget": "current"}
        session.commit()
        live = session.get(User, owner_id)
        expected = {
            "secret": live.totp_secret_ref,
            "step": live.totp_last_step,
            "codes": list(live.recovery_code_hashes),
            "later": added.id,
        }
    return root, stage, owner_id, member_id, task_id, old_codes, fresh_codes, expected, member_device.token


def test_restoring_older_data_preserves_current_password_mfa_roles_and_rate_budget(private_backup):
    root, stage, owner_id, member_id, task_id, old_codes, fresh_codes, expected, old_cookie = private_backup
    authority = current_security(root / "db/ai-station.sqlite")
    result = normalize_copy(stage, authority, str(uuid4()))
    assert result["accounts_preserved"] == 3 and result["account_sessions_revoked"] == 2
    engine = create_engine(f"sqlite:///{stage}")
    try:
        with Session(engine) as session:
            owner = session.get(User, owner_id)
            assert password_matches(owner.password_record, NEW) and not password_matches(
                owner.password_record, OLD
            )
            assert owner.totp_secret_ref == expected["secret"] and owner.totp_last_step == expected["step"]
            assert owner.recovery_code_hashes == expected["codes"] and owner.totp_enabled_at is not None
            assert not session.get(User, member_id).enabled
            assert session.get(User, expected["later"]).enabled
            assert session.get(Task, task_id).owner_id == owner_id
            assert all(row.revoked_at is not None for row in session.scalars(select(UserSession)))
            assert not list(session.scalars(select(UserSetting).where(UserSetting.key.startswith("auth."))))
            assert session.get(Setting, "account_attempts:login").value == {"synthetic_budget": "current"}
            assert accounts.authenticate(session, old_cookie) is None
            with pytest.raises(accounts.AccountError):
                accounts.login(session, "Owner", NEW, second_factor=old_codes[2])
            session.rollback()
            assert (
                accounts.login(session, "Owner", NEW, second_factor=fresh_codes[0]).principal.user_id
                == owner_id
            )
    finally:
        engine.dispose()


def test_unreadable_current_authority_never_revives_backup_accounts_with_an_operator_password(private_backup):
    _, stage, *_ = private_backup
    original = stage.read_bytes()
    with pytest.raises(RecoveryError, match="account authority is unavailable"):
        normalize_copy(stage, None, str(uuid4()), password="synthetic operator recovery password")
    assert stage.read_bytes() == original


def test_conflicting_account_identity_requires_mapping_before_any_recovery_is_applied(private_backup):
    root, stage, owner_id, *_ = private_backup
    authority = current_security(root / "db/ai-station.sqlite")
    for row in authority["account_authority"]:
        if row["id"] == owner_id:
            row["id"] = str(uuid4())
    original = stage.read_bytes()
    with pytest.raises(RecoveryError, match="identity differs"):
        normalize_copy(stage, authority, str(uuid4()))
    assert stage.read_bytes() == original
