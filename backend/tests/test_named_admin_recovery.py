"""Physical, explicit recovery never silently restores historical authority."""

import json
import shutil
from uuid import uuid4

import pytest
from app import accounts
from app.account_credentials import password_matches
from app.db import control_session_factory, reset_engine
from app.models import Setting, Task, User, UserSession
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from station_recovery import cli, host, operation
from station_recovery.accounts import AdminRecovery
from station_recovery.storage import RecoveryError, current_security, normalize_copy
from test_account_offline_recovery import NEW, OLD
from test_account_offline_recovery import private_backup as private_backup
from test_account_private_api import private_app as private_app

RECOVERED = "synthetic recovered administrator password"
MEMBER = "synthetic fresh member password"


def test_private_access_stays_disabled_after_named_recovery_without_legacy_operator_credentials(
    private_backup,
):
    stage = private_backup[1]
    engine = create_engine(f"sqlite:///{stage}")
    try:
        with Session(engine) as session:
            session.add(
                Setting(
                    key="private_ui_access",
                    value={"enabled": True, "revision": 4, "origin": "https://synthetic.example"},
                )
            )
            session.commit()
        normalize_copy(
            stage, None, str(uuid4()), admin_recovery=AdminRecovery("Owner", RECOVERED, reset_mfa=True)
        )
        with Session(engine) as session:
            policy = session.get(Setting, "private_ui_access").value
            assert not policy["enabled"] and policy["password_required"] and policy["origin"] is None
            assert session.get(Setting, "operator_auth") is None
    finally:
        engine.dispose()


def test_named_recovery_requires_new_admin_authority_and_explicit_member_reenrollment(private_backup):
    root, stage, owner_id, member_id, task_id, *_ = private_backup
    secret = root / private_backup[7]["secret"].removeprefix("file:")
    original_secret = secret.read_bytes()
    result = normalize_copy(
        stage, None, str(uuid4()), admin_recovery=AdminRecovery("OWNER", RECOVERED, reset_mfa=True)
    )
    assert result["administrator_recovered"] == owner_id
    assert result["accounts_quarantined"] == 1 and result["account_sessions_revoked"] == 2
    engine = create_engine(f"sqlite:///{stage}")
    try:
        with Session(engine) as session:
            owner = session.get(User, owner_id)
            assert owner.is_admin and owner.enabled and not owner.legacy_operator
            assert owner.totp_enabled_at is None and owner.recovery_code_hashes == []
            assert password_matches(owner.password_record, RECOVERED)
            assert not password_matches(owner.password_record, OLD) and not password_matches(
                owner.password_record, NEW
            )
            member = session.get(User, member_id)
            assert not member.enabled and not member.is_admin and member.password_record == {}
            assert session.get(Task, task_id).owner_id == owner_id
            assert all(row.revoked_at for row in session.scalars(select(UserSession)))
            actor = accounts.login(session, "Owner", RECOVERED).principal
            with pytest.raises(accounts.AccountError, match="before enabling"):
                accounts.update_user(session, actor, member_id, enabled=True, is_admin=False)
            with pytest.raises(accounts.AccountError, match="Reset two-factor"):
                accounts.reset_user_credentials(
                    session, actor, member_id, admin_password=RECOVERED, new_password=MEMBER
                )
            accounts.reset_user_credentials(
                session, actor, member_id, admin_password=RECOVERED, new_password=MEMBER, reset_mfa=True
            )
            accounts.update_user(session, actor, member_id, enabled=True, is_admin=False)
            session.commit()
            assert accounts.login(session, "Member", MEMBER).principal.user_id == member_id
    finally:
        engine.dispose()
    assert secret.read_bytes() == original_secret


@pytest.mark.parametrize(
    "name,reset,error",
    [
        ("Owner", False, "explicit --reset-admin-mfa"),
        ("Member", True, "administrator present"),
        ("Unknown", True, "administrator present"),
    ],
)
def test_incomplete_or_nonadministrator_recovery_does_not_modify_staging(private_backup, name, reset, error):
    stage = private_backup[1]
    original = stage.read_bytes()
    with pytest.raises(RecoveryError, match=error):
        normalize_copy(
            stage, None, str(uuid4()), admin_recovery=AdminRecovery(name, RECOVERED, reset_mfa=reset)
        )
    assert stage.read_bytes() == original


def test_readable_current_authority_cannot_be_replaced_by_a_named_backup_reset(private_backup):
    root, stage, *_ = private_backup
    original = stage.read_bytes()
    with pytest.raises(RecoveryError, match="only for unreadable authority"):
        normalize_copy(
            stage,
            current_security(root / "db/ai-station.sqlite"),
            str(uuid4()),
            admin_recovery=AdminRecovery("Owner", RECOVERED, reset_mfa=True),
        )
    assert stage.read_bytes() == original


@pytest.mark.parametrize(
    "flags",
    [
        ["--recover-admin", "Owner"],
        ["--reset-admin-mfa"],
        ["--admin-password-file", "unused"],
        [
            "--recover-admin",
            "Owner",
            "--reset-admin-mfa",
            "--apply",
            "--expected-sha256",
            "a" * 64,
            "--operator-password-file",
            "unused",
        ],
    ],
)
def test_cli_requires_explicit_nonconflicting_recovery_options(flags):
    with pytest.raises(SystemExit) as error:
        cli.main(["--backup-run", str(uuid4()), *flags])
    assert error.value.code == 2


def test_recovery_request_repr_does_not_expose_password():
    assert RECOVERED not in repr(AdminRecovery("Owner", RECOVERED, reset_mfa=True))


def test_actual_cli_recovers_corrupt_database_and_new_account_login(
    private_backup, private_app, monkeypatch, tmp_path, capsys
):
    root, stage, owner_id, member_id, task_id, *_ = private_backup
    backup_id = str(uuid4())
    folder = root / "backups"
    folder.mkdir(exist_ok=True)
    backup = folder / f"{backup_id}.sqlite"
    shutil.copyfile(stage, backup)
    backup.chmod(0o600)
    digest = operation.file_hash(backup)
    for name in ("assert_no_containers", "assert_no_native_groups", "assert_no_database_users"):
        monkeypatch.setattr(operation, name, lambda _root: None)
        monkeypatch.setitem(host.offline_guard.__wrapped__.__globals__, name, lambda _root: None)
    reset_engine()
    current = root / "db/ai-station.sqlite"
    current.write_bytes(b"synthetic corrupt current database")
    password_file = tmp_path / "admin-password.txt"
    password_file.write_text(RECOVERED)
    password_file.chmod(0o600)
    assert (
        cli.main(
            [
                "--data-root",
                str(root),
                "--backup-run",
                backup_id,
                "--apply",
                "--expected-sha256",
                digest,
                "--recover-admin",
                "Owner",
                "--reset-admin-mfa",
                "--admin-password-file",
                str(password_file),
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    assert receipt["applied"] and not receipt["automatic_replay"]
    assert receipt["actions"]["administrator_recovered"] == owner_id
    assert receipt["rollback_backup_id"] is None
    assert RECOVERED not in output.out and "password_record" not in output.out
    assert (
        root / "recovery" / receipt["recovery_id"] / "original.sqlite"
    ).read_bytes() == b"synthetic corrupt current database"
    assert operation.file_hash(backup) == digest
    with control_session_factory()() as session:
        assert session.get(Task, task_id).owner_id == owner_id
        assert not session.get(User, member_id).enabled
    with TestClient(private_app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as browser:
        response = browser.post("/api/auth/login", json={"username": "Owner", "password": RECOVERED})
        assert response.status_code == 200 and response.json()["user"]["id"] == owner_id
        assert (
            browser.post("/api/auth/login", json={"username": "Member", "password": OLD}).status_code == 401
        )
