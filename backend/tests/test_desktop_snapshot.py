"""Actual SQLite snapshot/WAL semantics; marker authority has separate Docker checks."""

import hashlib
import os
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest
from app import desktop_snapshot as snapshot
from app import desktop_storage as storage


@pytest.fixture
def files(tmp_path, monkeypatch):
    source = tmp_path / "database"
    source.mkdir(mode=0o700)
    output = tmp_path / "export"
    output.mkdir(mode=0o700)
    monkeypatch.setattr(storage, "ROOT", source)
    monkeypatch.setattr(storage, "inspect", lambda value: value)
    monkeypatch.setattr(snapshot, "OUTPUT", output)
    value = storage.binding("a" * 32, "b" * 64, os.geteuid(), os.getegid())
    old = os.umask(0o077)
    try:
        yield source, output, value
    finally:
        os.umask(old)


def seed(source, *, wal=False):
    code = """import os,sqlite3,sys
os.umask(0o077)
c=sqlite3.connect(sys.argv[1])
c.execute('CREATE TABLE alembic_version(version_num TEXT)')
c.execute("INSERT INTO alembic_version VALUES ('0042')")
c.execute('CREATE TABLE private_rows(value TEXT)')
c.commit()
if sys.argv[2]=='wal':c.execute('PRAGMA journal_mode=WAL')
c.execute('INSERT INTO private_rows VALUES (?)',('Zażółć gęślą jaźń',));c.commit()
if sys.argv[2]=='wal':os._exit(0)
c.close()
"""
    subprocess.run(
        [sys.executable, "-c", code, str(source / "ai-station.sqlite"), "wal" if wal else "delete"],
        check=True,
    )


@pytest.mark.parametrize("wal", [False, True])
def test_export_includes_committed_wal_even_without_source_shm_and_never_changes_original(files, wal):
    source, output, value = files
    seed(source, wal=wal)
    if wal:
        (source / "ai-station.sqlite-shm").unlink()
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.iterdir()}
    operation = str(uuid4())
    result = snapshot.export_database(value, operation, "sha256:" + "c" * 64)
    with sqlite3.connect(output / "database.sqlite") as copied:
        assert copied.execute("SELECT value FROM private_rows").fetchall() == [("Zażółć gęślą jaźń",)]
        assert copied.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    assert result["operation_id"] == operation and result["database_revision"] == "0042"
    assert result["database_sha256"] == hashlib.sha256((output / "database.sqlite").read_bytes()).hexdigest()
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.iterdir()} == before
    assert sorted(p.name for p in output.iterdir()) == ["database.sqlite", "receipt.json"]


@pytest.mark.parametrize("entry", ["partial-output", "symlink", "hardlink"])
def test_export_refuses_existing_output_and_unsafe_sources_without_publishing_receipt(files, entry):
    source, output, value = files
    seed(source)
    main = source / "ai-station.sqlite"
    if entry == "partial-output":
        (output / "keep").write_text("retained incomplete export")
    elif entry == "hardlink":
        os.link(main, source / "other")
    else:
        main.rename(source / "original")
        main.symlink_to(source / "original")
    with pytest.raises((ValueError, OSError)):
        snapshot.export_database(value, str(uuid4()), "sha256:" + "c" * 64)
    assert not (output / "receipt.json").exists()


def test_changed_source_during_clone_keeps_original_and_partial_copy_for_inspection(files, monkeypatch):
    source, output, value = files
    seed(source)
    copy = snapshot.copy_fixed

    def changed(*args):
        copy(*args)
        with sqlite3.connect(source / "ai-station.sqlite") as c:
            c.execute("INSERT INTO private_rows VALUES ('changed during copy')")

    monkeypatch.setattr(snapshot, "copy_fixed", changed)
    with pytest.raises(ValueError, match="changed"):
        snapshot.export_database(value, str(uuid4()), "sha256:" + "c" * 64)
    assert not (output / "receipt.json").exists()
    assert (output / "staging/ai-station.sqlite").exists()


def test_corrupt_database_cannot_publish_a_successful_snapshot(files):
    source, output, value = files
    (source / "ai-station.sqlite").write_bytes(b"not SQLite")
    with pytest.raises(sqlite3.Error):
        snapshot.export_database(value, str(uuid4()), "sha256:" + "c" * 64)
    assert not (output / "receipt.json").exists()
