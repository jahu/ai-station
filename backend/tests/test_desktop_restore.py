"""Actual image-local SQL restore contracts, disposable DBs and no real executors."""

import fcntl
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app import desktop_restore as restore
from app import desktop_snapshot as snapshot
from app import desktop_storage as storage
from app.account_credentials import make_password_record
from app.accounts import authenticate
from app.db import control_session_factory, migrate, reset_engine
from app.models import Agent, Conversation, Run, User, UserSession
from sqlalchemy import select
from test_desktop_upgrade import saved  # noqa: F401

IMAGE = "sha256:" + "c" * 64
SNAPSHOT = "d" * 64


@pytest.fixture
def setup(saved, tmp_path, monkeypatch):  # noqa: F811
    root, operation, token = saved
    value = storage.binding("a" * 32, "b" * 64, os.geteuid(), os.getegid())
    monkeypatch.setattr(storage, "ROOT", root / "db")
    monkeypatch.setattr(storage, "inspect", lambda value: value)
    output = tmp_path / "standalone"
    output.mkdir(mode=0o700)
    monkeypatch.setattr(snapshot, "OUTPUT", output)
    backup = str(uuid4())
    snapshot.export_database(value, backup, IMAGE)
    monkeypatch.setattr(restore, "INPUT", output / "database.sqlite")
    authority = tmp_path / "administrator.json"
    monkeypatch.setattr(restore, "AUTHORITY", authority)
    old = os.umask(0o077)
    try:
        yield SimpleNamespace(
            root=root,
            operation=operation,
            token=token,
            value=value,
            backup=backup,
            digest=snapshot.digest(restore.INPUT),
            authority=authority,
        )
    finally:
        reset_engine()
        os.umask(old)


def prepare(setup, **kwargs):
    return restore.prepare(
        setup.value, setup.operation, setup.backup, SNAPSHOT, setup.digest, IMAGE, **kwargs
    )


def current(setup):
    return storage.fingerprint(setup.value)["database"]


def test_restore_stages_then_preserves_current_password_mfa_and_revokes_old_work(setup):
    with control_session_factory()() as session:
        owner = session.scalar(select(User).where(User.bootstrap_pending.is_(False)))
        owner.password_record = make_password_record("newer private account password")
        owner.totp_secret_ref = "private-current-MFA-reference"
        owner.totp_last_step = 123456
        expected = owner.password_record
        conversation = session.scalar(select(Conversation))
        conversation.title = "Newer conversation before restore"
        session.commit()
    reset_engine()
    before = current(setup)
    result = prepare(setup)
    assert result["phase"] == "prepared" and current(setup) == before
    assert result["actions"]["runs_interrupted"] == 1 and result["actions"]["agents_paused"] == 1
    assert restore.status(setup.value, setup.operation, IMAGE) == result
    stamp = (restore.folder(setup.operation) / "original.sqlite").stat().st_mtime_ns
    assert prepare(setup) == result
    assert (restore.folder(setup.operation) / "original.sqlite").stat().st_mtime_ns == stamp
    assert restore.publish(setup.value, setup.operation, IMAGE)["phase"] == "applied"
    assert not (storage.ROOT / restore.MARKER).exists()
    migrate()
    with control_session_factory()() as session:
        assert session.scalar(select(Conversation)).title == "Retained conversation"
        owner = session.scalar(select(User).where(User.bootstrap_pending.is_(False)))
        assert owner.password_record == expected
        assert owner.totp_secret_ref == "private-current-MFA-reference" and owner.totp_last_step == 123456
        assert not session.scalar(select(Agent)).enabled
        run = session.scalar(select(Run))
        assert run.status == "interrupted" and run.retry_class == "inspect"
        assert all(row.revoked_at for row in session.scalars(select(UserSession)))
        assert authenticate(session, setup.token) is None
    assert (setup.root / "artifacts/keep.txt").read_text() == "existing artifact bytes"
    assert "newer private account password" not in json.dumps(result)


def test_lost_publication_ack_resumes_without_replacing_or_normalizing_twice(setup, monkeypatch):
    prepare(setup)
    original = restore.os.replace
    lost = False

    def replace(source, target):
        nonlocal lost
        original(source, target)
        if str(target).endswith("/ai-station.sqlite") and not lost:
            lost = True
            raise OSError("synthetic lost database replacement acknowledgement")

    monkeypatch.setattr(restore.os, "replace", replace)
    with pytest.raises(OSError, match="lost database"):
        restore.publish(setup.value, setup.operation, IMAGE)
    assert restore.status(setup.value, setup.operation, IMAGE)["phase"] == "publishing"
    before = current(setup)
    result = restore.publish(setup.value, setup.operation, IMAGE)
    assert result["phase"] == "applied" and current(setup) == before
    assert restore.publish(setup.value, setup.operation, IMAGE) == result
    assert restore.status(setup.value, setup.operation, IMAGE) == result


def test_hot_wal_restore_resumes_after_sidecars_removed_before_replacement(setup, monkeypatch):
    code = """import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA journal_mode=WAL')
c.execute("UPDATE conversations SET title='newer value in WAL'");c.commit();os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(storage.ROOT / "ai-station.sqlite")], check=True)
    before = current(setup)
    assert before["-wal"] is not None
    prepare(setup)
    assert current(setup) == before
    original = restore.os.replace

    def interrupt(source, target):
        if str(target).endswith("/ai-station.sqlite"):
            raise OSError("synthetic exit before swap")
        original(source, target)

    monkeypatch.setattr(restore.os, "replace", interrupt)
    with pytest.raises(OSError, match="before swap"):
        restore.publish(setup.value, setup.operation, IMAGE)
    assert current(setup) == {**before, "-wal": None}
    monkeypatch.setattr(restore.os, "replace", original)
    assert restore.publish(setup.value, setup.operation, IMAGE)["phase"] == "applied"
    with closing(sqlite3.connect(storage.ROOT / "ai-station.sqlite")) as db:
        assert db.execute("SELECT title FROM conversations").fetchone() == ("Retained conversation",)
    assert snapshot.digest(restore.folder(setup.operation) / "original.sqlite-wal") == before["-wal"]


@pytest.mark.parametrize("point", ["migration", "normalization"])
def test_interrupted_preparation_can_reconstruct_only_its_unpublished_stage(setup, monkeypatch, point):
    _, helpers = restore.recovery()
    name = "migrate_copy" if point == "migration" else "normalize_copy"
    original = getattr(helpers, name)

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic preparation interruption")

    before = current(setup)
    monkeypatch.setattr(helpers, name, interrupted)
    with pytest.raises(RuntimeError, match="preparation interruption"):
        prepare(setup)
    assert current(setup) == before
    monkeypatch.setattr(helpers, name, original)
    assert prepare(setup)["phase"] == "prepared" and current(setup) == before


@pytest.mark.parametrize("entry", ["staged.sqlite", "original.sqlite", "live"])
def test_changed_prepared_or_original_database_is_never_overwritten(setup, entry):
    prepare(setup)
    target = (
        storage.ROOT / "ai-station.sqlite" if entry == "live" else restore.folder(setup.operation) / entry
    )
    with target.open("ab") as changed:
        changed.write(b"changed bytes")
    before = current(setup)
    with pytest.raises(ValueError, match="changed"):
        restore.publish(setup.value, setup.operation, IMAGE)
    assert current(setup) == before and (storage.ROOT / restore.MARKER).exists()


def test_abort_preserves_original_and_does_not_repeat_after_later_writes(setup):
    before = current(setup)
    prepare(setup)
    result = restore.abort(setup.value, setup.operation, IMAGE)
    assert result["phase"] == "aborted" and current(setup) == before
    assert not (storage.ROOT / restore.MARKER).exists()
    with (storage.ROOT / "ai-station.sqlite").open("ab") as changed:
        changed.write(b"later writes")
    assert restore.abort(setup.value, setup.operation, IMAGE) == result


def test_pending_volume_restore_blocks_actual_api_migration(setup):
    from app.api import app
    from fastapi.testclient import TestClient

    prepare(setup)
    before = current(setup)
    with pytest.raises(RuntimeError, match="pending private restore"):
        migrate()
    with pytest.raises(RuntimeError, match="pending private restore"):
        with TestClient(app):
            pass
    assert current(setup) == before


def test_pending_restore_cannot_be_exported_or_hidden_by_an_upgrade(setup, monkeypatch, tmp_path):
    from app import desktop_upgrade

    prepare(setup)
    before = current(setup)
    output = tmp_path / "another-export"
    output.mkdir(mode=0o700)
    monkeypatch.setattr(snapshot, "OUTPUT", output)
    with pytest.raises(ValueError, match="pending private restore"):
        snapshot.export_database(setup.value, str(uuid4()), IMAGE)
    with pytest.raises(RuntimeError, match="pending private restore"):
        desktop_upgrade.prepare(setup.root, str(uuid4()), "e" * 64, "f" * 64)
    assert current(setup) == before and not list(output.iterdir())


def test_unreadable_authority_requires_explicit_private_named_admin_reset(setup):
    (storage.ROOT / "ai-station.sqlite").write_bytes(b"corrupt current database")
    before = current(setup)
    with pytest.raises(ValueError, match="explicit administrator"):
        prepare(setup)
    assert current(setup) == before
    restore.abort(setup.value, setup.operation, IMAGE)
    setup.operation = str(uuid4())
    password = "explicit new recovered password"
    setup.authority.write_text(json.dumps({"username": "Owner", "password": password, "reset_mfa": True}))
    result = prepare(setup, recover_admin=True)
    assert result["phase"] == "prepared" and result["actions"]["administrator_mfa_reset"]
    assert password not in (restore.folder(setup.operation) / "request.json").read_text()
    assert password not in json.dumps(result)
    assert restore.publish(setup.value, setup.operation, IMAGE)["phase"] == "applied"
    from app.account_credentials import password_matches

    with closing(sqlite3.connect(storage.ROOT / "ai-station.sqlite")) as db:
        record, secret = db.execute(
            "SELECT password_record,totp_secret_ref FROM users WHERE normalized_username='owner'"
        ).fetchone()
        assert password_matches(json.loads(record), password) and secret is None


def test_changed_private_recovery_password_cannot_resume_the_same_preparation(setup):
    (storage.ROOT / "ai-station.sqlite").write_bytes(b"corrupt current database")
    setup.authority.write_text(
        json.dumps({"username": "Owner", "password": "explicit new recovered password", "reset_mfa": True})
    )
    prepare(setup, recover_admin=True)
    setup.authority.write_text(
        json.dumps({"username": "Owner", "password": "a different recovery password", "reset_mfa": True})
    )
    with pytest.raises(ValueError, match="recovery request changed"):
        prepare(setup, recover_admin=True)


def test_readable_current_authority_cannot_be_replaced_with_a_backup_admin_reset(setup):
    setup.authority.write_text(
        json.dumps({"username": "Owner", "password": "explicit new recovered password", "reset_mfa": True})
    )
    before = current(setup)
    with pytest.raises(ValueError, match="unreadable authority"):
        prepare(setup, recover_admin=True)
    assert current(setup) == before


@pytest.mark.parametrize("entry", ["source-link", "source-sidecar", "stage-link"])
def test_restore_file_boundaries_preserve_external_files_and_live_db(setup, entry):
    before = current(setup)
    if entry == "source-link":
        original = restore.INPUT.with_name("original.sqlite")
        restore.INPUT.rename(original)
        restore.INPUT.symlink_to(original)
    elif entry == "source-sidecar":
        restore.INPUT.with_name(restore.INPUT.name + "-wal").write_bytes(b"unknown WAL")
    else:
        prepare(setup)
        stage = restore.folder(setup.operation) / "staged.sqlite"
        stage.unlink()
        stage.symlink_to(restore.INPUT)
    with pytest.raises((OSError, ValueError)):
        prepare(setup) if entry != "stage-link" else restore.publish(setup.value, setup.operation, IMAGE)
    assert current(setup) == before
    assert snapshot.digest(restore.INPUT.resolve()) == setup.digest


def test_held_volume_restore_lock_refuses_a_second_helper(setup):
    path = storage.ROOT / ".desktop-restore.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="helper is active"):
            prepare(setup)
    finally:
        os.close(fd)


def test_insufficient_disk_preserves_original_and_can_abort(setup, monkeypatch):
    before = current(setup)
    monkeypatch.setattr(restore.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="space for staging"):
        prepare(setup)
    assert current(setup) == before
    assert restore.abort(setup.value, setup.operation, IMAGE)["phase"] == "aborted"


@pytest.mark.parametrize("action,phase", [("publish", "applied"), ("abort", "aborted")])
def test_completed_receipt_resumes_only_marker_cleanup_after_parent_exit(setup, monkeypatch, action, phase):
    prepared = prepare(setup)
    original = restore.finish

    def interrupted(request, state):
        raise RuntimeError("synthetic exit after terminal receipt")

    monkeypatch.setattr(restore, "finish", interrupted)
    with pytest.raises(RuntimeError, match="terminal receipt"):
        getattr(restore, action)(setup.value, setup.operation, IMAGE)
    assert restore.status(setup.value, setup.operation, IMAGE)["phase"] == phase
    before = current(setup)
    assert (storage.ROOT / restore.MARKER).exists()
    monkeypatch.setattr(restore, "finish", original)
    result = getattr(restore, action)(setup.value, setup.operation, IMAGE)
    assert result["phase"] == phase and current(setup) == before
    assert result["database_sha256"] == prepared["database_sha256"]
    assert not (storage.ROOT / restore.MARKER).exists()


def test_late_wal_writer_cannot_hide_behind_an_applied_main_file_hash(setup, monkeypatch):
    prepare(setup)
    original = restore.finish
    monkeypatch.setattr(
        restore, "finish", lambda *_: (_ for _ in ()).throw(RuntimeError("exit before cleanup"))
    )
    with pytest.raises(RuntimeError, match="before cleanup"):
        restore.publish(setup.value, setup.operation, IMAGE)
    code = """import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE late_writer(value TEXT)');c.commit();os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(storage.ROOT / "ai-station.sqlite")], check=True)
    before = current(setup)
    assert before["-wal"] is not None
    monkeypatch.setattr(restore, "finish", original)
    with pytest.raises(ValueError, match="before restore completion"):
        restore.publish(setup.value, setup.operation, IMAGE)
    assert current(setup) == before and (storage.ROOT / restore.MARKER).exists()


def test_interrupted_original_copy_reconstructs_only_fixed_unpublished_scratch(setup, monkeypatch):
    original = snapshot.copy_fixed
    before = current(setup)

    def interrupted(source, target):
        if target.name == "original.sqlite.part":
            target.write_bytes(b"partial unpublished copy")
            raise OSError("synthetic exit during original copy")
        return original(source, target)

    monkeypatch.setattr(snapshot, "copy_fixed", interrupted)
    with pytest.raises(OSError, match="original copy"):
        prepare(setup)
    assert current(setup) == before
    monkeypatch.setattr(snapshot, "copy_fixed", original)
    assert prepare(setup)["phase"] == "prepared"
    assert current(setup) == before
    assert snapshot.digest(restore.folder(setup.operation) / "original.sqlite") == before["main"]


def test_cross_filesystem_stage_is_rejected_before_publication_intent(setup, monkeypatch):
    prepare(setup)
    before = current(setup)
    monkeypatch.setattr(
        restore.upgrade, "filesystem_mount", lambda p: "stage" if restore.STORE in p.parts else "target"
    )
    with pytest.raises(ValueError, match="another filesystem"):
        restore.publish(setup.value, setup.operation, IMAGE)
    assert restore.status(setup.value, setup.operation, IMAGE)["phase"] == "prepared"
    assert current(setup) == before
    assert restore.abort(setup.value, setup.operation, IMAGE)["phase"] == "aborted"
