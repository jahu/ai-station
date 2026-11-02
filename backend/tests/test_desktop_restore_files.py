"""Real retained-file publication/rollback, no SQLite, commands or real user files."""

import os
from uuid import uuid4

import desktop_restore_files as restore
import desktop_snapshot_files as files
import pytest

IDENTITY = "c" * 64


@pytest.fixture
def tree(tmp_path):
    tmp_path = tmp_path / "retained-files"
    tmp_path.mkdir(mode=0o700)
    source, data, backup = (tmp_path / name for name in ("source", "data", "backup"))
    old = os.umask(0o077)
    try:
        for root in (source, data, backup):
            root.mkdir(mode=0o700)
        for root in (source, data):
            for name in ("artifacts", "secrets", "uploads", "runtime", "db"):
                (root / name).mkdir(mode=0o700)
            (root / "artifacts/photo.bin").write_bytes(b"older image" if root == source else b"newer image")
            (root / "secrets/connector").write_bytes(b"same credential")
            (root / "runtime/processes.json").write_text("never restored")
            (root / "db/ai-station.sqlite").write_text("never native SQL")
        (source / "uploads/Żółw.txt").write_text("older upload")
        (data / "secrets/new-MFA").write_text("newer MFA key")
        files.export_files(source, backup, IDENTITY)
        yield source, data, backup
    finally:
        os.umask(old)


def test_prepare_publish_and_commit_keep_current_MFA_and_never_execution_authority(tree):
    _, data, backup = tree
    before = restore.inventory(data)
    operation = str(uuid4())
    owner = restore.FileRestore(data, operation)
    assert owner.prepare(backup, IDENTITY)["phase"] == "prepared"
    assert restore.inventory(data) == before
    assert owner.publish()["phase"] == "published"
    assert (data / "artifacts/photo.bin").read_bytes() == b"older image"
    assert (data / "uploads/Żółw.txt").read_text() == "older upload"
    assert (data / "secrets/new-MFA").read_text() == "newer MFA key"
    assert (data / "runtime/processes.json").read_text() == "never restored"
    assert (data / "db/ai-station.sqlite").read_text() == "never native SQL"
    assert (owner.originals / "artifacts/photo.bin").read_bytes() == b"newer image"
    assert owner.commit()["phase"] == "committed"
    with pytest.raises(ValueError, match="automatic file rollback"):
        owner.abort()


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
def test_exit_after_any_atomic_root_move_can_resume_or_rollback(tree, monkeypatch, count):
    _, data, backup = tree
    before = restore.inventory(data)
    operation = str(uuid4())
    owner = restore.FileRestore(data, operation)
    owner.prepare(backup, IDENTITY)
    move = owner.move
    calls = 0

    def interrupted(*args):
        nonlocal calls
        move(*args)
        calls += 1
        if calls == count:
            raise RuntimeError("synthetic exit after move")

    monkeypatch.setattr(owner, "move", interrupted)
    with pytest.raises(RuntimeError, match="after move"):
        owner.publish()
    resumed = restore.FileRestore(data, operation)
    if count % 2:
        assert resumed.publish()["phase"] == "published"
        assert (data / "artifacts/photo.bin").read_bytes() == b"older image"
    assert resumed.abort()["phase"] == "aborted"
    assert restore.inventory(data) == before


def test_interrupted_staging_preserves_originals_and_reuses_verified_copies(tree):
    _, data, backup = tree
    before = restore.inventory(data)
    owner = restore.FileRestore(data, str(uuid4()))

    def interrupted(done, total):
        if done == 2:
            raise RuntimeError("synthetic staging exit")

    with pytest.raises(RuntimeError):
        owner.prepare(backup, IDENTITY, progress=interrupted)
    copied = owner.incoming / "artifacts/photo.bin"
    stamp = copied.stat().st_mtime_ns
    assert owner.prepare(backup, IDENTITY)["phase"] == "prepared"
    assert copied.stat().st_mtime_ns == stamp
    assert restore.inventory(data) == before
    owner.abort()


def test_current_credential_conflict_requires_review_and_preserves_current_value(tree):
    _, data, backup = tree
    (data / "secrets/connector").write_text("newer connector credential")
    owner = restore.FileRestore(data, str(uuid4()))
    with pytest.raises(restore.SecretConflict) as found:
        owner.prepare(backup, IDENTITY)
    assert found.value.paths == ["secrets/connector"]
    assert not (owner.root / "request.json").exists()
    owner.prepare(backup, IDENTITY, secrets_policy="keep_current")
    owner.publish()
    assert (data / "secrets/connector").read_text() == "newer connector credential"


def test_changed_source_or_stage_cannot_replace_current_files(tree):
    _, data, backup = tree
    owner = restore.FileRestore(data, str(uuid4()))
    owner.prepare(backup, IDENTITY)
    (owner.incoming / "artifacts/photo.bin").write_text("tampered staged image")
    with pytest.raises(ValueError, match="changed"):
        owner.publish()
    assert (data / "artifacts/photo.bin").read_bytes() == b"newer image"


def test_external_reference_is_not_restored_but_internal_links_remain_portable(tree):
    source, data, _ = tree
    outside = source.parent / "external-model"
    outside.write_bytes(b"do not copy or modify")
    (source / "artifacts/internal").symlink_to("photo.bin")
    (source / "artifacts/external").symlink_to(outside)
    backup = source.parent / "linked-backup"
    backup.mkdir(mode=0o700)
    files.export_files(source, backup, IDENTITY)
    owner = restore.FileRestore(data, str(uuid4()))
    owner.prepare(backup, IDENTITY)
    owner.publish()
    assert (data / "artifacts/internal").read_bytes() == b"older image"
    assert not (data / "artifacts/external").is_symlink()
    assert outside.read_bytes() == b"do not copy or modify"


def test_original_absolute_internal_link_is_preserved_by_rollback(tree):
    _, data, backup = tree
    (data / "artifacts/current-link").symlink_to(data / "artifacts/photo.bin")
    before = restore.inventory(data)
    owner = restore.FileRestore(data, str(uuid4()))
    owner.prepare(backup, IDENTITY)
    owner.publish()
    owner.abort()
    assert restore.inventory(data) == before
    assert os.readlink(data / "artifacts/current-link") == str(data / "artifacts/photo.bin")


def test_unknown_live_file_during_partial_publication_is_preserved(tree):
    _, data, backup = tree
    owner = restore.FileRestore(data, str(uuid4()))
    owner.prepare(backup, IDENTITY)
    owner.publish()
    (data / "unrelated.txt").write_text("new human content")
    with pytest.raises(ValueError, match="changed"):
        owner.publish()
    assert (data / "unrelated.txt").read_text() == "new human content"


def test_abort_before_publication_preserves_later_human_edits(tree):
    _, data, backup = tree
    owner = restore.FileRestore(data, str(uuid4()))
    owner.prepare(backup, IDENTITY)
    (data / "artifacts/photo.bin").write_text("new human edit")
    owner.abort()
    assert (data / "artifacts/photo.bin").read_text() == "new human edit"


def test_exit_after_request_before_initial_state_is_recoverable(tree, monkeypatch):
    _, data, backup = tree
    owner = restore.FileRestore(data, str(uuid4()))
    save = owner.save
    monkeypatch.setattr(owner, "save", lambda *_: (_ for _ in ()).throw(RuntimeError("exit before state")))
    with pytest.raises(RuntimeError):
        owner.prepare(backup, IDENTITY)
    monkeypatch.setattr(owner, "save", save)
    assert owner.prepare(backup, IDENTITY)["phase"] == "prepared"
    owner.abort()


def test_missing_state_after_publication_never_restarts_preparation(tree):
    _, data, backup = tree
    owner = restore.FileRestore(data, str(uuid4()))
    owner.prepare(backup, IDENTITY)
    owner.publish()
    (owner.root / "state.json").unlink()
    with pytest.raises(ValueError, match="requires inspection"):
        owner.prepare(backup, IDENTITY)
    assert (data / "artifacts/photo.bin").read_bytes() == b"older image"


def test_tampered_root_path_cannot_move_files_outside_application_storage(tree):
    import json

    _, data, backup = tree
    owner = restore.FileRestore(data, str(uuid4()))
    owner.prepare(backup, IDENTITY)
    request = json.loads((owner.root / "request.json").read_text())
    request["original_roots"]["../outside"] = [1, 1]
    files.write_json(owner.root / "request.json", request)
    with pytest.raises(ValueError, match="inventory changed"):
        owner.publish()
    assert (data / "artifacts/photo.bin").read_bytes() == b"newer image"
