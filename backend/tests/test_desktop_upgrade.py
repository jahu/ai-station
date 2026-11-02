"""Real disposable SQLite upgrades; no production database, Docker or models."""

import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from app import db as database
from app import desktop_upgrade as upgrade
from app.accounts import authenticate, bootstrap_admin, login
from app.config import get_settings
from app.db import alembic_config, control_session_factory, migrate, reset_engine
from app.models import Agent, Conversation
from app.runs import create_run, create_task
from fastapi.testclient import TestClient
from launch import ensure_recovery_finished
from sqlalchemy import URL, create_engine

PREVIOUS, TARGET = "a" * 64, "b" * 64


def installer_permissions(root):
    # Normal tests inherit the developer's cooperative umask. The desktop
    # installer creates private owned storage; do not relax production checks.
    for path in (root, root / "db", root / "runtime"):
        path.chmod(0o700)
    for path in (root / "db/ai-station.sqlite", root / "runtime/migrations.lock"):
        if path.exists():
            path.chmod(0o600)


def rows(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {
            name: sorted(db.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr)
            for name in tables
        }


@pytest.fixture
def saved():
    root = get_settings().data_dir.resolve()
    with control_session_factory()() as session:
        user = bootstrap_admin(session, "Owner", "synthetic upgrade account password", local_setup=True)
        session.commit()
        grant = login(session, "Owner", "synthetic upgrade account password", remember_me=True)
        session.add(Conversation(title="Retained conversation", owner_id=user.id))
        session.add(
            Agent(name="Retained enabled agent", goal="Keep schedule", enabled=True, owner_id=user.id)
        )
        task = create_task(
            session, title="Retained task", prompt="Private synthetic prompt", capability="test"
        )
        create_run(session, task, run_type="test", capability="test", executor_type="fake")
        session.commit()
        token = grant.token
    reset_engine()  # Real offline handoff, not concurrent live SQLite ownership.
    installer_permissions(root)
    artifact = root / "artifacts/keep.txt"
    artifact.write_text("existing artifact bytes")
    return root, str(uuid4()), token


@pytest.fixture
def legacy_saved():
    root = get_settings().data_dir.resolve()
    reset_engine()
    legacy = root / "db/.legacy-upgrade-fixture.sqlite"
    engine = create_engine(URL.create("sqlite", database=str(legacy)))
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "0041")
    finally:
        engine.dispose()
    os.replace(legacy, root / "db/ai-station.sqlite")
    installer_permissions(root)
    return root, str(uuid4()), None


def prepare(saved):
    root, identity, _ = saved
    return upgrade.prepare(root, identity, PREVIOUS, TARGET)


def test_prepare_publish_preserves_all_rows_cookie_agents_jobs_and_artifact(saved):
    root, identity, token = saved
    path = root / "db/ai-station.sqlite"
    before, source = rows(path), upgrade.fingerprint(root)
    result = prepare(saved)
    assert result["phase"] == "prepared" and upgrade.fingerprint(root) == source
    assert rows(root / result["backup_relative"]) == before
    assert (root / result["backup_relative"]).stat().st_mode & 0o777 == 0o600
    assert prepare(saved) == result  # Exact prepared resume never rewrites its backup.
    assert upgrade.publish(root, identity)["phase"] == "applied"
    assert rows(path) == before
    assert not (root / "runtime" / upgrade.MARKER).exists()
    assert (root / "artifacts/keep.txt").read_text() == "existing artifact bytes"
    migrate()
    with control_session_factory()() as session:
        assert authenticate(session, token) is not None
    assert "synthetic upgrade account password" not in json.dumps(result)


def test_pending_upgrade_blocks_api_migration_and_supervisor_start(saved):
    from app.api import app

    root, _, _ = saved
    prepare(saved)
    before = upgrade.fingerprint(root)
    with pytest.raises(RuntimeError, match="pending offline desktop upgrade"):
        migrate()
    with pytest.raises(RuntimeError, match="pending offline desktop upgrade"):
        ensure_recovery_finished(root / "runtime")
    with pytest.raises(RuntimeError, match="pending offline desktop upgrade"):
        with TestClient(app):
            pass
    assert upgrade.fingerprint(root) == before


def test_api_rechecks_pending_upgrade_after_waiting_for_migration_lock(saved, monkeypatch):
    root, _, _ = saved
    reached, errors = threading.Event(), []
    original = database.require_upgrade_finished

    def observe(path):
        original(path)
        reached.set()

    monkeypatch.setattr(database, "require_upgrade_finished", observe)

    def start():
        try:
            migrate()
        except Exception as error:
            errors.append(error)

    with (root / "runtime/migrations.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        worker = threading.Thread(target=start)
        worker.start()
        assert reached.wait(5)
        (root / "runtime" / upgrade.MARKER).write_text("pending fixture")
    worker.join(timeout=10)
    assert not worker.is_alive() and len(errors) == 1 and isinstance(errors[0], RuntimeError)
    assert "pending offline desktop upgrade" in str(errors[0])


def test_safe_abort_keeps_source_and_original_backup(saved):
    root, identity, _ = saved
    before = upgrade.fingerprint(root)
    result = prepare(saved)
    backup = root / result["backup_relative"]
    retained = backup.read_bytes()
    assert upgrade.abort(root, identity)["phase"] == "aborted"
    assert upgrade.fingerprint(root) == before and backup.read_bytes() == retained
    assert not (root / "runtime" / upgrade.MARKER).exists()
    assert upgrade.abort(root, identity)["phase"] == "aborted"
    migrate()


def test_lost_success_acknowledgement_is_read_only_after_new_application_writes(saved):
    root, identity, _ = saved
    prepare(saved)
    result = upgrade.publish(root, identity)
    with closing(sqlite3.connect(root / "db/ai-station.sqlite")) as db:
        db.execute("CREATE TABLE qa_after_update(value TEXT)")
        db.execute("INSERT INTO qa_after_update VALUES ('new application data')")
        db.commit()
    before = upgrade.fingerprint(root)
    with (root / "runtime/launcher.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        assert upgrade.status(root, identity) == result
        assert upgrade.publish(root, identity) == result
    assert upgrade.fingerprint(root) == before


@pytest.mark.parametrize("action,phase", [("abort", "aborted"), ("publish", "applied")])
def test_completion_resumes_if_process_exits_after_receipt_before_fence_removal(
    saved, monkeypatch, action, phase
):
    root, identity, _ = saved
    prepare(saved)
    before = rows(root / "db/ai-station.sqlite")
    operation = {"abort": upgrade.abort, "publish": upgrade.publish}[action]
    original = Path.unlink

    def interrupted(path, *args, **kwargs):
        if path == root / "runtime" / upgrade.MARKER:
            raise SystemExit("synthetic exit after completion receipt")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupted)
        with pytest.raises(SystemExit):
            operation(root, identity)
    assert (root / "runtime" / upgrade.MARKER).exists()
    assert operation(root, identity)["phase"] == phase
    assert rows(root / "db/ai-station.sqlite") == before
    assert not (root / "runtime" / upgrade.MARKER).exists()


def test_unicode_spaces_and_uri_characters_use_only_explicit_staging_connection(saved):
    root, identity, _ = saved
    moved = root.with_name("Application Support Łódź, 100% #?")
    before = rows(root / "db/ai-station.sqlite")
    root.rename(moved)
    upgrade.prepare(moved, identity, PREVIOUS, TARGET)
    upgrade.publish(moved, identity)
    assert rows(moved / "db/ai-station.sqlite") == before
    assert not root.exists()  # Config still names old root; Alembic must not use it.


@pytest.mark.parametrize(
    "url",
    ["sqlite:///:memory:", "sqlite:////unrelated/database.sqlite", "postgresql://neutral.invalid/station"],
)
def test_installer_cli_refuses_external_database_override_before_any_upgrade_write(saved, monkeypatch, url):
    import app.config

    root, identity, _ = saved
    with monkeypatch.context() as patch:
        patch.setattr(
            app.config, "get_settings", lambda: SimpleNamespace(data_dir=root, sqlite_url=lambda: url)
        )
        patch.setattr(
            sys,
            "argv",
            [
                "desktop_upgrade",
                "prepare",
                "--operation-id",
                identity,
                "--previous-bundle",
                PREVIOUS,
                "--target-bundle",
                TARGET,
            ],
        )
        patch.setattr(upgrade.signal, "signal", lambda *args: None)
        previous_mask = os.umask(0o077)
        try:
            with pytest.raises(ValueError, match="standard app-owned SQLite"):
                upgrade.main()
        finally:
            os.umask(previous_mask)
    assert not (root / "desktop-upgrades").exists()


def test_migration_failure_preserves_original_and_allows_safe_abort(saved, monkeypatch):
    root, identity, _ = saved
    before = upgrade.fingerprint(root)

    def failure(*args, **kwargs):
        raise RuntimeError("neutral staged migration failure")

    monkeypatch.setattr(upgrade.command, "upgrade", failure)
    with pytest.raises(RuntimeError, match="staged migration failure"):
        prepare(saved)
    assert upgrade.fingerprint(root) == before
    assert (root / "desktop-upgrades" / identity / "original.sqlite").exists()
    assert upgrade.abort(root, identity)["phase"] == "aborted"


def test_failed_copy_removes_only_its_incomplete_file_and_keeps_source(saved, monkeypatch):
    root, identity, _ = saved
    before = upgrade.fingerprint(root)
    original_connect = sqlite3.connect

    class ReadOnlySource:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def backup(self, target):
            target.execute("CREATE TABLE qa_partial(value TEXT)")
            target.commit()
            raise OSError("synthetic disk-full copy failure")

    def connect(path, *args, **kwargs):
        connection = original_connect(path, *args, **kwargs)
        return ReadOnlySource(connection) if isinstance(path, str) and "?mode=ro" in path else connection

    with monkeypatch.context() as patch:
        patch.setattr(upgrade.sqlite3, "connect", connect)
        with pytest.raises(OSError, match="disk-full"):
            prepare(saved)
    assert not (root / "desktop-upgrades" / identity / "original.sqlite").exists()
    assert upgrade.fingerprint(root) == before
    result = upgrade.abort(root, identity)
    assert result["phase"] == "aborted" and result["backup_verified"] is False


@pytest.mark.parametrize("after_replace", [False, True])
def test_interrupted_publication_resumes_same_operation_without_recopied_backup(
    legacy_saved, monkeypatch, after_replace
):
    root, identity, _ = legacy_saved
    before = rows(root / "db/ai-station.sqlite")
    result = prepare(legacy_saved)
    backup = root / result["backup_relative"]
    backup_identity = (backup.read_bytes(), backup.stat().st_mtime_ns)
    original = upgrade.os.replace

    def crash(source, destination):
        if Path(destination) == root / "db/ai-station.sqlite":
            if after_replace:
                original(source, destination)
            raise SystemExit("synthetic process exit during publication")
        return original(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(upgrade.os, "replace", crash)
        with pytest.raises(SystemExit):
            upgrade.publish(root, identity)
    assert (root / "runtime" / upgrade.MARKER).exists()
    with pytest.raises(ValueError, match="Publication began"):
        upgrade.abort(root, identity)
    assert upgrade.publish(root, identity)["phase"] == "applied"
    after = rows(root / "db/ai-station.sqlite")
    assert before.pop("alembic_version") == [("0041",)]
    assert after.pop("alembic_version") == [("0042",)]
    assert after == before
    assert (backup.read_bytes(), backup.stat().st_mtime_ns) == backup_identity


@pytest.mark.parametrize("change", ["original", "stage", "backup", "target"])
def test_changed_inputs_cannot_be_adopted_or_published(saved, change):
    root, identity, _ = saved
    prepare(saved)
    folder = root / "desktop-upgrades" / identity
    if change == "target":
        with pytest.raises(ValueError, match="input changed"):
            upgrade.prepare(root, identity, PREVIOUS, "c" * 64)
    else:
        path = (
            root / "db/ai-station.sqlite"
            if change == "original"
            else folder / ("staged.sqlite" if change == "stage" else "original.sqlite")
        )
        with path.open("ab") as target:
            target.write(b"changed bytes")
        with pytest.raises(ValueError, match="changed"):
            upgrade.publish(root, identity)
    assert (root / "runtime" / upgrade.MARKER).exists()
    if change == "stage":
        assert upgrade.abort(root, identity)["phase"] == "aborted"


def test_hot_wal_is_backed_up_and_publication_resumes_after_sidecar_removal(saved, monkeypatch):
    root, identity, _ = saved
    path = root / "db/ai-station.sqlite"
    subprocess.run(
        [
            sys.executable,
            "-IB",
            "-c",
            "import sqlite3,sys,os;db=sqlite3.connect(sys.argv[1]);db.execute('PRAGMA journal_mode=WAL');"
            "db.execute('CREATE TABLE qa_hot(value TEXT)');db.execute(\"INSERT INTO qa_hot VALUES ('retained WAL data')\");"
            "db.commit();os._exit(0)",
            str(path),
        ],
        check=True,
        timeout=10,
    )
    assert upgrade.fingerprint(root)["-wal"] is not None
    before = rows(path)
    result = prepare(saved)
    assert rows(root / result["backup_relative"]) == before
    original = upgrade.os.replace

    def crash(source, destination):
        if Path(destination) == path:
            assert not path.with_name(path.name + "-wal").exists()
            raise SystemExit("synthetic exit after sidecar removal")
        return original(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(upgrade.os, "replace", crash)
        with pytest.raises(SystemExit):
            upgrade.publish(root, identity)
    assert (root / "runtime" / upgrade.MARKER).exists()
    assert upgrade.publish(root, identity)["phase"] == "applied"
    assert rows(path) == before


@pytest.mark.parametrize("name", ["launcher.lock", "migrations.lock"])
def test_live_owner_or_migration_prevents_creating_upgrade_state(saved, name):
    root, _, _ = saved
    with (root / "runtime" / name).open("a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="Stop the owned station"):
            prepare(saved)
    assert not (root / "runtime" / upgrade.MARKER).exists()


@pytest.mark.parametrize("kind", ["database-link", "sidecar-link", "backup-directory-link", "hardlink"])
def test_file_boundaries_refuse_links_without_mutating_external_data(saved, tmp_path, kind):
    root, _, _ = saved
    outside = tmp_path / "outside"
    outside.write_text("unrelated original bytes")
    database = root / "db/ai-station.sqlite"
    if kind == "database-link":
        database.unlink()
        database.symlink_to(outside)
    elif kind == "sidecar-link":
        database.with_name(database.name + "-wal").symlink_to(outside)
    elif kind == "backup-directory-link":
        (root / "desktop-upgrades").symlink_to(root / "artifacts", target_is_directory=True)
    else:
        os.link(database, tmp_path / "linked-database")
    with pytest.raises(ValueError):
        prepare(saved)
    assert outside.read_text() == "unrelated original bytes"
