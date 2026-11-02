"""Fixed image file attestation, separate from native quiescence/marker integration."""

import hashlib
import os

import pytest
from app import desktop_storage as storage


@pytest.fixture
def files(tmp_path, monkeypatch):
    tmp_path = tmp_path / "database"
    tmp_path.mkdir(mode=0o700)
    tmp_path.chmod(0o700)
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    # This family isolates byte/path safety. Root-marker ownership is tested by
    # the real isolated Docker lifecycle, not fabricated with unprivileged files.
    monkeypatch.setattr(storage, "inspect", lambda value: value)
    value = storage.binding("a" * 32, "b" * 64, os.geteuid(), os.getegid())
    previous_umask = os.umask(0o077)
    try:
        (tmp_path / "ai-station.sqlite").write_bytes(b"synthetic database bytes")
        yield tmp_path, value
    finally:
        os.umask(previous_umask)


def test_fixed_main_and_wal_hashes_match_backend_activation_shape_without_writes(files):
    root, value = files
    (root / "ai-station.sqlite-wal").write_bytes(b"synthetic pending WAL")
    (root / "ai-station.sqlite-journal").touch()
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}
    result = storage.fingerprint(value)
    assert result == {
        "storage": value,
        "database": {
            "main": hashlib.sha256(b"synthetic database bytes").hexdigest(),
            "-wal": hashlib.sha256(b"synthetic pending WAL").hexdigest(),
            "-journal": None,
        },
    }
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()} == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "shared-write", "fifo"])
def test_unsafe_fixed_database_file_is_refused_without_reading_other_paths(files, kind):
    root, value = files
    main = root / "ai-station.sqlite"
    if kind == "shared-write":
        main.chmod(0o664)
    elif kind == "hardlink":
        os.link(main, root / "other")
    else:
        main.unlink()
        if kind == "symlink":
            outside = root.parent / "outside"
            outside.write_bytes(b"unrelated bytes")
            main.symlink_to(outside)
        else:
            os.mkfifo(main)
    with pytest.raises((ValueError, OSError)):
        storage.fingerprint(value)


def test_nonempty_rollback_journal_requires_inspection(files):
    root, value = files
    journal = root / "ai-station.sqlite-journal"
    journal.write_bytes(b"unfinished transaction")
    with pytest.raises(ValueError, match="unfinished SQLite journal"):
        storage.fingerprint(value)
    assert journal.read_bytes() == b"unfinished transaction"


@pytest.mark.parametrize("replace", [False, True])
def test_database_mutation_or_replacement_during_hashing_is_not_attested(files, monkeypatch, replace):
    root, value = files
    original = hashlib.file_digest

    def modified(source, algorithm):
        result = original(source, algorithm)
        path = root / "ai-station.sqlite"
        if replace:
            path.unlink()
        path.write_bytes(b"changed during read")
        return result

    monkeypatch.setattr(storage.hashlib, "file_digest", modified)
    with pytest.raises(ValueError, match="bytes changed"):
        storage.fingerprint(value)
