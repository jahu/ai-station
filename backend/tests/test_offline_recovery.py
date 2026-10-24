"""Recovery qualifies only disposable app data; never use the operator database."""

import hashlib
import runpy
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from app.config import get_settings
from app.db import session_factory
from app.models import Agent
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
