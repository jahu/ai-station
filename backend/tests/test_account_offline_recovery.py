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


@pytest.fixture
def legacy_account_backup(private_backup):
    import shutil

    from alembic import command
    from app.db import alembic_config
    from app.models import Artifact, Run
    from station_recovery.storage import migrate_copy

    root = private_backup[0]
    stage = root / "legacy-account-source.sqlite"
    engine = create_engine(f"sqlite:///{stage}")
    task_id, run_id, artifact_id = (str(uuid4()) for _ in range(3))
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "0036")
            connection.execute(Task.__table__.insert().values(id=task_id, title="Original legacy task"))
            connection.execute(
                Run.__table__.insert().values(
                    id=run_id, task_id=task_id, capability="test", executor_type="fake"
                )
            )
            connection.execute(
                Artifact.__table__.insert().values(
                    id=artifact_id,
                    run_id=run_id,
                    artifact_type="text",
                    relative_path="artifacts/legacy-account.txt",
                    mime_type="text/plain",
                    size_bytes=3,
                )
            )
            connection.execute(
                Setting.__table__.insert().values(
                    key="conversation_preferences", value={"model": "legacy-local", "version": 1}
                )
            )
    finally:
        engine.dispose()
    (root / "artifacts/legacy-account.txt").write_bytes(b"old")
    shutil.copyfile(stage, root / "legacy-before-accounts.sqlite")
    migrate_copy(stage)
    return stage, task_id, run_id, artifact_id


def test_explicit_legacy_owner_mapping_retains_ids_files_preferences_and_current_mfa(
    private_backup, legacy_account_backup
):
    from app.models import Artifact, Run

    root, _, owner_id, *_ = private_backup
    stage, task_id, run_id, artifact_id = legacy_account_backup
    result = normalize_copy(
        stage, current_security(root / "db/ai-station.sqlite"), str(uuid4()), legacy_owner="OWNER"
    )
    assert result["legacy_owner_mapping"]["owner_id"] == owner_id and result["accounts_preserved"] == 3
    previous = result["legacy_owner_mapping"]["previous_owner_id"]
    engine = create_engine(f"sqlite:///{stage}")
    try:
        with Session(engine) as session:
            assert session.get(User, previous) is None
            assert session.get(Task, task_id).owner_id == owner_id
            assert session.get(Run, run_id).owner_id == owner_id
            assert session.get(Artifact, artifact_id).owner_id == owner_id
            assert (
                session.scalar(
                    select(UserSetting).where(UserSetting.key == "conversation_preferences")
                ).user_id
                == owner_id
            )
            assert session.get(User, owner_id).totp_enabled_at is not None
            assert session.connection().exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert (root / "artifacts/legacy-account.txt").read_bytes() == b"old"
    finally:
        engine.dispose()


@pytest.mark.parametrize("owner", [None, "MissingPerson"])
def test_legacy_data_is_never_assigned_to_a_guessed_or_unknown_person(
    private_backup, legacy_account_backup, owner
):
    root = private_backup[0]
    stage = legacy_account_backup[0]
    original = stage.read_bytes()
    with pytest.raises(RecoveryError, match="mapping|existing current account"):
        normalize_copy(
            stage, current_security(root / "db/ai-station.sqlite"), str(uuid4()), legacy_owner=owner
        )
    assert stage.read_bytes() == original


def test_explicit_mapping_does_not_reassign_a_backup_containing_multiple_private_accounts(private_backup):
    root, stage, *_ = private_backup
    original = stage.read_bytes()
    with pytest.raises(RecoveryError, match="one unambiguous"):
        normalize_copy(
            stage, current_security(root / "db/ai-station.sqlite"), str(uuid4()), legacy_owner="Owner"
        )
    assert stage.read_bytes() == original


def test_legacy_owner_cli_option_requires_explicit_apply_and_backup_digest():
    from station_recovery.cli import main

    with pytest.raises(SystemExit) as error:
        main(["--backup-run", str(uuid4()), "--legacy-owner", "Owner"])
    assert error.value.code == 2


def test_same_initial_owner_uuid_survives_bootstrap_rename_and_reuse_of_admin_name(
    private_backup, legacy_account_backup
):
    from app.data_access import ROOTS
    from sqlalchemy import update

    root, _, owner_id, *_ = private_backup
    stage = legacy_account_backup[0]
    engine = create_engine(f"sqlite:///{stage}")
    try:
        with Session(engine) as session:
            initial = session.scalar(select(User))
            previous = initial.id
            for model in ROOTS:
                session.execute(update(model).where(model.owner_id == previous).values(owner_id=owner_id))
            session.execute(
                update(UserSetting).where(UserSetting.user_id == previous).values(user_id=owner_id)
            )
            initial.id = owner_id
            session.commit()
        with control_session_factory()() as session:
            live_owner = session.get(User, owner_id)
            # Trusted fixture insert simulates the current directory; current
            # password/MFA authority still comes from the read-only snapshot.
            named_admin = User(username="admin", normalized_username="admin", enabled=False)
            session.add(named_admin)
            session.commit()
            other_id, current_name = named_admin.id, live_owner.username
        normalize_copy(
            stage, current_security(root / "db/ai-station.sqlite"), str(uuid4()), legacy_owner="Owner"
        )
        with Session(engine) as session:
            assert session.get(User, owner_id).username == current_name
            assert session.get(User, other_id).username == "admin"
            assert session.get(Task, legacy_account_backup[1]).owner_id == owner_id
            assert session.connection().exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def test_cli_performs_guarded_legacy_restore_without_logging_current_credentials(
    private_backup, legacy_account_backup, monkeypatch, capsys
):
    import json
    import shutil

    from app.db import reset_engine
    from station_recovery import cli, host, operation

    root, _, owner_id, *_ = private_backup
    backup_id = str(uuid4())
    folder = root / "backups"
    folder.mkdir(exist_ok=True)
    backup = folder / f"{backup_id}.sqlite"
    shutil.copyfile(root / "legacy-before-accounts.sqlite", backup)
    backup.chmod(0o600)
    digest = operation.file_hash(backup)
    for name in ("assert_no_containers", "assert_no_native_groups", "assert_no_database_users"):
        monkeypatch.setattr(operation, name, lambda _root: None)
        monkeypatch.setitem(host.offline_guard.__wrapped__.__globals__, name, lambda _root: None)
    reset_engine()
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
                "--legacy-owner",
                "Owner",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    assert receipt["applied"] and not receipt["automatic_replay"]
    assert receipt["actions"]["legacy_owner_mapping"]["owner_id"] == owner_id
    assert NEW not in output.out and OLD not in output.out and "password_record" not in output.out
    assert operation.file_hash(backup) == digest
    with control_session_factory()() as session:
        assert password_matches(session.get(User, owner_id).password_record, NEW)
        assert session.get(Task, legacy_account_backup[1]).owner_id == owner_id
        assert session.connection().exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert (root / "backups" / f"{receipt['rollback_backup_id']}.sqlite").is_file()
