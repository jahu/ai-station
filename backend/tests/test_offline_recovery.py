"""Recovery qualifies only disposable app data; never use the operator database."""

import fcntl
import hashlib
import json
import os
import runpy
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.config import get_settings
from app.db import session_factory
from app.models import Agent, Run
from app.runs import create_run, create_task

restore = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/restore.py"))
inspect_backup = restore["inspect_backup"]
RecoveryError = restore["RecoveryError"]


@pytest.fixture
def backup():
    root = get_settings().data_dir
    with session_factory()() as session:
        task = create_task(session, title="Retained task", prompt="Do not replay", capability="test")
        create_run(session, task, run_type="test", capability="test", executor_type="fake")
        session.add(Agent(name="Paused on recovery", goal="No automatic execution", enabled=True))
        session.commit()
    folder = root / "backups"
    folder.mkdir(exist_ok=True)
    bid = str(uuid4())
    path = folder / (bid + ".sqlite")
    with (
        closing(sqlite3.connect(root / "db/ai-station.sqlite")) as source,
        closing(sqlite3.connect(path)) as target,
    ):
        source.backup(target)
    return root, bid, path


def test_inspection_is_read_only_and_reports_uncertain_work_without_credentials(backup):
    root, bid, path = backup
    original = path.read_bytes()
    files = sorted(p.relative_to(root) for p in root.rglob("*"))
    result = inspect_backup(root, bid)
    assert result["schema_revision"] == "0033"
    assert result["counts"]["tasks"] == result["counts"]["runs"] == 1
    assert result["agents_to_pause"] == result["runs_requiring_inspection"] == 1
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    assert result["database_only"] and result["sessions_will_be_revoked"]
    assert not result["applied"] and not result["automatic_replay"]
    assert result["missing_artifact_files"] == 0
    assert path.read_bytes() == original
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == files
    with session_factory()() as session:
        assert session.query(Agent).one().enabled


@pytest.mark.parametrize("kind", ["corrupt", "schema", "sidecar", "hardlink", "symlink"])
def test_recovery_rejects_untrusted_or_incompatible_backup_without_mutating_live_data(backup, tmp_path, kind):
    root, bid, path = backup
    before = (root / "db/ai-station.sqlite").read_bytes()
    if kind == "corrupt":
        path.write_bytes(b"not a SQLite backup")
    elif kind == "schema":
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE alembic_version SET version_num='future'")
            connection.commit()
    elif kind == "sidecar":
        Path(str(path) + "-wal").write_bytes(b"uncheckpointed")
    elif kind == "hardlink":
        (root / "backups/other.sqlite").hardlink_to(path)
    else:
        outside = tmp_path / "unrelated.sqlite"
        path.replace(outside)
        path.symlink_to(outside)
    with pytest.raises(RecoveryError, match="schema revision" if kind == "schema" else None):
        inspect_backup(root, bid)
    assert (root / "db/ai-station.sqlite").read_bytes() == before


def test_missing_or_escaped_artifact_files_remain_a_recovery_blocker(backup, tmp_path):
    from app.models import Artifact

    root, bid, path = backup
    # App-owned artifact metadata in the backup must never escape its data root.
    with session_factory()() as session:
        session.add(
            Artifact(
                artifact_type="document",
                mime_type="text/plain",
                relative_path="artifacts/missing.txt",
                size_bytes=1,
                sha256="a" * 64,
            )
        )
        session.commit()
    path.unlink()
    with (
        closing(sqlite3.connect(root / "db/ai-station.sqlite")) as source,
        closing(sqlite3.connect(path)) as target,
    ):
        source.backup(target)
    assert inspect_backup(root, bid)["missing_artifact_files"] == 1
    (root / "artifacts").mkdir(exist_ok=True)
    outside = tmp_path / "unrelated.txt"
    outside.write_text("Do not read this file")
    (root / "artifacts/missing.txt").symlink_to(outside)
    with pytest.raises(RecoveryError, match="symlink"):
        inspect_backup(root, bid)


@pytest.mark.parametrize("relationship", ["same", "parent", "child", "unrelated", "stopped"])
def test_container_guard_uses_data_mounts_without_reading_secrets_or_stopping_services(
    backup, monkeypatch, relationship
):
    root, _, _ = backup
    source = (
        root
        if relationship in {"same", "stopped"}
        else root.parent
        if relationship == "parent"
        else root / "runtime/model"
        if relationship == "child"
        else root.parent / "other-app"
    )
    calls = []

    def docker(argv, **kwargs):
        calls.append(argv)
        assert kwargs["check"] and kwargs["timeout"] == 20
        if argv[1] == "ps":
            return SimpleNamespace(stdout="abc123\n")
        assert argv[1:3] == ["inspect", "--format"]
        assert ".Mounts" in argv[3] and ".Config" not in argv[3]
        return SimpleNamespace(
            stdout=json.dumps(
                {"State": {"Running": relationship != "stopped"}, "Mounts": [{"Source": str(source)}]}
            )
            + "\n"
        )

    monkeypatch.setattr(subprocess, "run", docker)
    if relationship in {"same", "parent", "child"}:
        with pytest.raises(RecoveryError, match="Stop containers"):
            restore["assert_no_containers"](root)
    else:
        restore["assert_no_containers"](root)
    assert [c[1] for c in calls] == ["ps", "inspect"]


@pytest.mark.parametrize("state", ["alive", "gone", "unknown"])
def test_native_guard_never_assumes_unknown_ownership_means_a_dead_process(backup, monkeypatch, state):
    from ai_station_runner import processes

    root, _, _ = backup
    record = {"boot_id": "test", "start_ticks": 123} if state != "unknown" else {}
    (root / "runtime/processes.json").write_text(json.dumps({"run": record}))
    monkeypatch.setattr(processes, "_group_alive", lambda _record: state == "alive")
    if state == "gone":
        restore["assert_no_native_groups"](root)
    else:
        with pytest.raises(RecoveryError):
            restore["assert_no_native_groups"](root)


def test_active_launcher_refuses_recovery_before_host_probes(backup, monkeypatch):
    root, _, _ = backup
    globals_ = restore["offline_guard"].__wrapped__.__globals__

    def unexpected(_root):
        raise AssertionError("Do not inspect or mutate an actively supervised deployment")

    monkeypatch.setitem(globals_, "assert_no_containers", unexpected)
    fd = os.open(root / "runtime/launcher.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RecoveryError, match="supervisor"):
            with restore["offline_guard"](root):
                raise AssertionError("Recovery must not start")
    finally:
        os.close(fd)


def test_open_database_handle_blocks_recovery_even_without_a_compose_service(backup, monkeypatch):
    root, _, _ = backup
    code = "import pathlib,sys,time;f=pathlib.Path(sys.argv[1]).open('rb');print('ready',flush=True);time.sleep(30)"
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(root / "db/ai-station.sqlite")], stdout=subprocess.PIPE, text=True
    )
    monkeypatch.setitem(
        restore["assert_no_database_users"].__globals__,
        "process_entries",
        lambda: [Path("/proc") / str(process.pid)],
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(RecoveryError, match="database connection"):
            restore["assert_no_database_users"](root)
    finally:
        process.terminate()
        process.wait(timeout=5)
    restore["assert_no_database_users"](root)


@pytest.fixture
def fake_host(monkeypatch):
    globals_ = restore["restore_database"].__globals__
    for key in ("assert_no_containers", "assert_no_native_groups", "assert_no_database_users"):
        monkeypatch.setitem(globals_, key, lambda _root: None)
    return globals_


def test_actual_database_swap_preserves_a_rollback_copy_and_pauses_restored_work(backup, fake_host):
    from app.db import reset_engine

    root, bid, path = backup
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    reset_engine()
    result = restore["restore_database"](root, bid, digest)
    assert result["applied"] and result["phase"] == "applied" and not result["automatic_replay"]
    assert result["actions"]["agents_paused"] == result["actions"]["runs_interrupted"] == 1
    assert result["rollback_backup_id"] == result["recovery_id"]
    assert not (root / "runtime/recovery-pending.json").exists()
    assert (root / "db/ai-station.sqlite").stat().st_mode & 0o077 == 0
    with closing(sqlite3.connect(root / "db/ai-station.sqlite")) as current:
        assert current.execute("SELECT enabled FROM agents").fetchone() == (0,)
        assert current.execute("SELECT status FROM runs").fetchone() == ("interrupted",)
    rollback = root / "backups" / (result["rollback_backup_id"] + ".sqlite")
    with closing(sqlite3.connect(rollback)) as previous:
        assert previous.execute("SELECT enabled FROM agents").fetchone() == (1,)
        assert previous.execute("SELECT status FROM runs").fetchone() == ("queued",)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("failure", ["before_replace", "after_replace"])
def test_interrupted_swap_retains_its_approved_stage_and_can_finish_without_replaying_work(
    backup, fake_host, monkeypatch, failure
):
    from app.db import reset_engine

    root, bid, path = backup
    reset_engine()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    original_replace = os.replace
    original_json = fake_host["private_json"]

    def replace(source, target):
        if Path(source).name.startswith(".restore-") and failure == "before_replace":
            raise OSError("simulated interruption before replacement")
        return original_replace(source, target)

    def json_write(path, value):
        if Path(path).name == "receipt.json" and value["phase"] == "applied" and failure == "after_replace":
            raise OSError("simulated interruption after replacement")
        return original_json(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace)
        patch.setitem(fake_host, "private_json", json_write)
        with pytest.raises(OSError, match="simulated interruption"):
            restore["restore_database"](root, bid, digest)
    pending = restore["read_private_json"](root / "runtime/recovery-pending.json")
    result = restore["resume_recovery"](root, pending["recovery_id"])
    assert result["applied"] and result["phase"] == "applied"
    assert not (root / "runtime/recovery-pending.json").exists()
    with closing(sqlite3.connect(root / "db/ai-station.sqlite")) as current:
        assert current.execute("SELECT enabled FROM agents").fetchone() == (0,)
        assert current.execute("SELECT status FROM runs").fetchone() == ("interrupted",)


def test_recovery_of_a_corrupt_current_database_keeps_raw_originals_and_requires_new_auth(backup, fake_host):
    from app.db import reset_engine
    from app.operator_auth import verify_password
    from sqlalchemy import URL, create_engine
    from sqlalchemy.orm import Session

    root, bid, path = backup
    reset_engine()
    (root / "db/ai-station.sqlite").write_bytes(b"damaged original")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RecoveryError, match="fresh operator password"):
        restore["restore_database"](root, bid, digest)
    result = restore["restore_database"](root, bid, digest, password="new-disaster-recovery-password")
    assert result["applied"] and result["rollback_backup_id"] is None
    assert (root / "recovery" / result["recovery_id"] / "original.sqlite").read_bytes() == b"damaged original"
    engine = create_engine(URL.create("sqlite", database=str(root / "db/ai-station.sqlite")))
    try:
        with Session(engine) as session:
            assert verify_password(session, "new-disaster-recovery-password")
    finally:
        engine.dispose()


def test_migration_receives_only_the_private_connection_and_supports_known_ancestors(backup):
    from alembic import command
    from sqlalchemy import URL, create_engine

    root, bid, path = backup
    stage = root / "legacy-staging.sqlite"
    engine = create_engine(URL.create("sqlite", database=str(stage)))
    try:
        with engine.begin() as connection:
            config = restore["migration_config"]()
            config.attributes["connection"] = connection
            command.upgrade(config, "0032")
    finally:
        engine.dispose()
    shutil.copyfile(stage, path)
    before = path.read_bytes()
    inspected = inspect_backup(root, bid)
    assert inspected["schema_revision"] == "0032"
    assert inspected["target_schema_revision"] == "0033" and inspected["migration_required"]
    restore["migrate_copy"](stage)
    with closing(sqlite3.connect(stage)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0033",)
        assert connection.execute("SELECT count(*) FROM tasks").fetchone() == (0,)
    assert path.read_bytes() == before
    with session_factory()() as session:
        assert session.query(Agent).one().enabled
        assert session.query(Run).one().status == "queued"


def test_staged_recovery_preserves_current_password_and_never_resumes_work_or_old_tokens(backup):
    from app.models import Approval, ResourceLock, RunEvent, RuntimeInstance, Setting, StationNode, WorkerRow
    from app.operator_auth import save_secret, verify_password
    from sqlalchemy import URL, create_engine, select
    from sqlalchemy.orm import Session

    root, bid, source = backup
    stage = root / "staging.sqlite"
    shutil.copyfile(source, stage)
    original = source.read_bytes()
    engine = create_engine(URL.create("sqlite", database=str(stage)))
    try:
        with Session(engine) as session:
            save_secret(session, "old-backup-password")
            session.add_all(
                [
                    Setting(key="operator_session", value={"token_hash": "old"}),
                    Setting(key="operator_session:stale", value={"token_hash": "stale"}),
                    Setting(key="operator_login_budget", value={"attempts": ["old"]}),
                    StationNode(name="Old invitation", token_hash="old-token", token_salt="ab" * 16),
                    RuntimeInstance(
                        name="Old managed", runtime_key="llama.cpp", ownership="managed", status="ready"
                    ),
                    RuntimeInstance(
                        name="External service", runtime_key="external", ownership="external", status="ready"
                    ),
                    WorkerRow(id="old-worker", hostname="old"),
                ]
            )
            run = session.query(Run).one()
            run.worker_id = "old-worker"
            run.metadata_json = {"inspection_acknowledged_at": "old"}
            session.query(Agent).one().last_status = "running"
            session.add(ResourceLock(resource_key="gpu:77", run_id=run.id))
            session.add(Approval(run_id=run.id, action="email.send", resolution="pending"))
            session.commit()
        with session_factory()() as session:
            save_secret(session, "current-operator-password")
            session.add(Setting(key="operator_login_budget", value={"attempts": ["current"]}))
            session.commit()
        security = restore["current_security"](root / "db/ai-station.sqlite")
        result = restore["normalize_copy"](stage, security, bid)
        assert result == {
            "agents_paused": 1,
            "runs_interrupted": 1,
            "sessions_revoked": 2,
            "node_tokens_revoked": 1,
            "approvals_denied": 1,
            "operator_password_reset": False,
            "automatic_replay": False,
        }
        with Session(engine) as session:
            assert verify_password(session, "current-operator-password")
            assert not verify_password(session, "old-backup-password")
            assert session.get(Setting, "operator_login_budget").value == {"attempts": ["current"]}
            assert not [s for s in session.scalars(select(Setting)) if s.key.startswith("operator_session")]
            agent = session.query(Agent).one()
            assert not agent.enabled and agent.next_run_at is None and agent.last_status == "interrupted"
            run = session.query(Run).one()
            assert run.status == "interrupted" and run.retry_class == "inspect" and run.worker_id is None
            assert "inspection_acknowledged_at" not in run.metadata_json
            assert session.query(ResourceLock).one().released_at
            assert session.query(WorkerRow).count() == 0
            assert {r.ownership: r.status for r in session.scalars(select(RuntimeInstance))} == {
                "managed": "stopped",
                "external": "unknown",
            }
            node = session.query(StationNode).one()
            assert node.status == "revoked" and not node.token_hash and not node.token_salt
            assert session.query(Approval).one().resolution == "denied"
            event = session.scalar(select(RunEvent).where(RunEvent.event_type == "run.interrupted"))
            assert event.payload["backup_run_id"] == bid
        assert source.read_bytes() == original
        with session_factory()() as session:
            assert session.query(Agent).one().enabled and session.query(Run).one().status == "queued"
    finally:
        engine.dispose()


def test_unreadable_current_security_requires_a_fresh_password_without_reviving_old_sessions(backup):
    from app.operator_auth import verify_password
    from sqlalchemy import URL, create_engine
    from sqlalchemy.orm import Session

    root, bid, source = backup
    stage = root / "staging.sqlite"
    shutil.copyfile(source, stage)
    before = stage.read_bytes()
    with pytest.raises(RecoveryError, match="fresh operator password"):
        restore["normalize_copy"](stage, None, bid)
    assert stage.read_bytes() == before
    result = restore["normalize_copy"](stage, None, bid, password="fresh-recovery-password")
    assert result["operator_password_reset"] and not result["automatic_replay"]
    engine = create_engine(URL.create("sqlite", database=str(stage)))
    try:
        with Session(engine) as session:
            assert verify_password(session, "fresh-recovery-password")
    finally:
        engine.dispose()
