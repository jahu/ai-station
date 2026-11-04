"""Native retained-file snapshot isolation and crash-resume, no DB or real workloads."""

import json
import os

import desktop_snapshot_files as files
import pytest

IDENTITY = "c" * 64


@pytest.fixture
def tree(tmp_path):
    # Backend checks also prepare tmp_path/data. Keep this native-only fixture
    # independently fresh rather than adopting that database tree.
    source, output = tmp_path.resolve() / "retained-data", tmp_path.resolve() / "snapshot"
    source.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    old = os.umask(0o077)
    try:
        for name in ("artifacts", "uploads", "secrets", "runtime", "cache", "db"):
            (source / name).mkdir(mode=0o700)
        (source / "artifacts/image.bin").write_bytes(b"synthetic image")
        (source / "uploads/Zażółć, notes.txt").write_text("private user source")
        (source / "secrets/credential").write_text("synthetic credential")
        (source / "runtime/processes.json").write_text("never execution authority")
        (source / "db/ai-station.sqlite").write_bytes(b"never opened by native files copier")
        yield source, output
    finally:
        os.umask(old)


def test_files_preserve_private_inputs_and_secrets_but_not_live_authority(tree):
    source, output = tree
    (source / "artifacts/alias").symlink_to("image.bin")
    outside = source.parent / "external-model"
    outside.write_bytes(b"external weights are not copied")
    (source / "artifacts/external").symlink_to(outside)
    report = files.export_files(source, output, IDENTITY)
    assert (output / "files/secrets/credential").read_text() == "synthetic credential"
    assert (output / "files/uploads/Zażółć, notes.txt").read_text() == "private user source"
    assert (output / "files/artifacts/alias").read_bytes() == b"synthetic image"
    assert not (output / "files/artifacts/external").exists()
    assert not (output / "files/db").exists() and not (output / "files/runtime").exists()
    assert (
        next(e for e in report["entries"] if e["path"] == "artifacts/external")["kind"]
        == "external_reference"
    )
    assert (output / "files/secrets/credential").stat().st_mode & 0o777 == 0o600
    assert (output / "files").stat().st_mode & 0o777 == 0o700


def test_resume_reuses_published_file_bytes_after_interruption(tree):
    source, output = tree

    def interrupted(count, total):
        if count == 2:
            raise RuntimeError("synthetic parent exit")

    with pytest.raises(RuntimeError):
        files.export_files(source, output, IDENTITY, progress=interrupted)
    image = output / "files/artifacts/image.bin"
    stamp = image.stat().st_mtime_ns
    result = files.export_files(source, output, IDENTITY)
    assert image.stat().st_mtime_ns == stamp
    assert result == json.loads((output / "files.json").read_text())


def test_changed_source_does_not_rewrite_a_partial_snapshot(tree):
    source, output = tree
    with pytest.raises(InterruptedError):
        files.export_files(source, output, IDENTITY, canceled=lambda: True)
    (source / "artifacts/image.bin").write_bytes(b"changed data")
    with pytest.raises(ValueError, match="changed since"):
        files.export_files(source, output, IDENTITY)
    assert not (output / "files.json").exists()


def test_cancel_mid_large_file_keeps_only_unpublished_scratch_and_resumes(tree):
    source, output = tree
    large = source / "artifacts/image.bin"
    large.write_bytes(b"x" * (3 * 1024**2))
    calls = 0

    def canceled():
        nonlocal calls
        calls += 1
        return calls == 4  # directory, file, first chunk, second chunk

    with pytest.raises(InterruptedError, match="while copying"):
        files.export_files(source, output, IDENTITY, canceled=canceled)
    assert not (output / "files/artifacts/image.bin").exists()
    scratch = list((output / "files-staging").iterdir())
    assert len(scratch) == 1 and scratch[0].stat().st_size == 1024**2
    files.export_files(source, output, IDENTITY)
    assert (output / "files/artifacts/image.bin").read_bytes() == large.read_bytes()
    assert not list((output / "files-staging").iterdir())


@pytest.mark.parametrize("kind", ["fifo", "hardlink", "shared-write"])
def test_unsafe_source_is_not_copied(tree, kind):
    source, output = tree
    target = source / "artifacts/image.bin"
    if kind == "fifo":
        target.unlink()
        os.mkfifo(target)
    elif kind == "hardlink":
        os.link(target, source / "artifacts/other")
    else:
        target.chmod(0o666)
    with pytest.raises(ValueError):
        files.export_files(source, output, IDENTITY)
    assert not (output / "files.json").exists()


def test_parent_directory_symlink_swap_cannot_copy_external_bytes(tree, monkeypatch):
    source, output = tree
    outside = source.parent / "outside"
    outside.mkdir(mode=0o700)
    (outside / "image.bin").write_bytes(b"outside private bytes")
    original = files.open_relative

    def swapped(root, key):
        if key == "artifacts/image.bin":
            (source / "artifacts").rename(source / "old-artifacts")
            (source / "artifacts").symlink_to(outside)
        return original(root, key)

    monkeypatch.setattr(files, "open_relative", swapped)
    with pytest.raises(OSError):
        files.export_files(source, output, IDENTITY)
    assert not (output / "files/artifacts/image.bin").exists()


def test_vm_database_and_case_alias_execution_directories_stay_excluded(tree):
    source, output = tree
    (source / "runtime").rename(source / "Runtime")
    (source / "artifacts/runtime-link").symlink_to("../Runtime/processes.json")
    result = files.export_files(source, output, IDENTITY)
    assert not (output / "files/Runtime").exists()
    assert (
        next(e for e in result["entries"] if e["path"] == "artifacts/runtime-link")["kind"]
        == "external_reference"
    )


@pytest.mark.parametrize("change", ["bytes", "extra", "runtime", "link_escape", "duplicate", "path_escape"])
def test_completed_files_manifest_refuses_tampering_before_restore(tree, change):
    source, output = tree
    (source / "artifacts/alias").symlink_to("image.bin")
    files.export_files(source, output, IDENTITY)
    if change == "bytes":
        (output / "files/artifacts/image.bin").write_bytes(b"corrupt snapshot")
    elif change in ("extra", "runtime"):
        name = "runtime" if change == "runtime" else "extra"
        (output / "files" / name).mkdir(mode=0o700)
    elif change == "link_escape":
        (output / "files/artifacts/alias").unlink()
        (output / "files/artifacts/alias").symlink_to(source / "secrets/credential")
    else:
        manifest = json.loads((output / "files.json").read_text())
        if change == "duplicate":
            manifest["entries"].append(manifest["entries"][0])
        else:
            manifest["entries"][0]["path"] = "../outside"
        files.write_json(output / "files.json", manifest)
    with pytest.raises(ValueError):
        files.verify_files(output, IDENTITY)


def test_completed_files_resume_keeps_manifest_and_data_mtime(tree):
    source, output = tree
    result = files.export_files(source, output, IDENTITY)
    paths = [output / "files.json", output / "files/artifacts/image.bin"]
    before = [p.stat().st_mtime_ns for p in paths]
    assert files.export_files(source, output, IDENTITY) == result
    assert [p.stat().st_mtime_ns for p in paths] == before
