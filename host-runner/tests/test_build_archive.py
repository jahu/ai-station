import hashlib
import os
import zipfile

import pytest
from ai_station_runner import build_archive


def sample(tmp_path):
    workspace = tmp_path / "worktree"
    (workspace / "dist/assets").mkdir(parents=True)
    (workspace / "dist/index.html").write_text('<script src="/assets/app.js"></script>')
    (workspace / "dist/assets/app.js").write_text('document.body.textContent="Built"')
    (workspace / ".env").write_text("DO NOT EXPORT")
    destination = tmp_path / "output.zip"
    return workspace, destination


def test_archive_captures_only_dist_as_data_and_reports_hash(tmp_path):
    workspace, destination = sample(tmp_path)
    report = build_archive.capture_build(workspace, destination, [{"kind": "build", "exit_code": 0}])
    assert report["status"] == "ready" and report["file_count"] == 2
    assert report["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert destination.stat().st_mode & 0o777 == 0o600 and destination.stat().st_nlink == 1
    with zipfile.ZipFile(destination) as archive:
        assert sorted(archive.namelist()) == ["assets/app.js", "index.html"]
        assert b"document.body" in archive.read("assets/app.js")
        assert sum(info.file_size for info in archive.infolist()) == report["uncompressed_bytes"]
    assert not destination.with_name(destination.name + ".partial").exists()
    assert (workspace / ".env").read_text() == "DO NOT EXPORT"


@pytest.mark.parametrize(
    "results",
    [
        [],
        [{"kind": "test", "exit_code": 0}],
        [{"kind": "build", "exit_code": 1}],
        [{"kind": "build", "exit_code": 0}, {"kind": "test", "exit_code": 1}],
    ],
)
def test_failed_or_non_build_checks_do_not_export(tmp_path, results):
    workspace, destination = sample(tmp_path)
    assert build_archive.capture_build(workspace, destination, results) is None
    assert not destination.exists()


@pytest.mark.parametrize(
    "kind",
    [
        "root_symlink",
        "directory_symlink",
        "file_symlink",
        "hardlink",
        "fifo",
        "hidden",
        "credentials",
        "node_modules",
    ],
)
def test_untrusted_output_cannot_escape_or_export_private_files(tmp_path, kind):
    workspace, destination = sample(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("PRIVATE")
    dist = workspace / "dist"
    if kind == "root_symlink":
        dist.rename(workspace / "saved")
        dist.symlink_to(tmp_path)
    elif kind == "directory_symlink":
        (dist / "redirect").symlink_to(tmp_path, target_is_directory=True)
    elif kind == "file_symlink":
        (dist / "redirect").symlink_to(outside)
    elif kind == "hardlink":
        (dist / "redirect").hardlink_to(outside)
    elif kind == "fifo":
        os.mkfifo(dist / "pipe")
    else:
        name = {"hidden": ".env", "credentials": "credentials.json", "node_modules": "node_modules"}[kind]
        (dist / name).write_text("PRIVATE")
    report = build_archive.capture_build(workspace, destination, [{"kind": "build", "exit_code": 0}])
    assert report["status"] == "unavailable"
    assert not destination.exists() and not list(tmp_path.glob("*.partial"))
    assert outside.read_text() == "PRIVATE"


@pytest.mark.parametrize("limit", ["files", "bytes", "empty", "missing"])
def test_output_bounds_and_absence_are_explicit(tmp_path, monkeypatch, limit):
    workspace, destination = sample(tmp_path)
    if limit == "files":
        monkeypatch.setattr(build_archive, "MAX_FILES", 1)
    elif limit == "bytes":
        monkeypatch.setattr(build_archive, "MAX_BYTES", 4)
    else:
        for file in (workspace / "dist").rglob("*"):
            if file.is_file():
                file.unlink()
        (workspace / "dist/assets").rmdir()
        if limit == "missing":
            (workspace / "dist").rmdir()
    assert (
        build_archive.capture_build(workspace, destination, [{"kind": "build", "exit_code": 0}])["status"]
        == "unavailable"
    )
    assert not destination.exists()


def test_existing_publication_is_never_overwritten(tmp_path):
    workspace, destination = sample(tmp_path)
    destination.write_text("KEEP")
    assert (
        build_archive.capture_build(workspace, destination, [{"kind": "build", "exit_code": 0}])["status"]
        == "unavailable"
    )
    assert destination.read_text() == "KEEP" and not list(tmp_path.glob("*.partial"))


def test_concurrent_output_change_prevents_archive_publication(tmp_path, monkeypatch):
    workspace, destination = sample(tmp_path)
    original = zipfile.ZipFile.writestr

    def changed(self, name, content, *args, **kwargs):
        result = original(self, name, content, *args, **kwargs)
        if name == "index.html":
            (workspace / "dist/index.html").write_text("changed after reading")
        return result

    monkeypatch.setattr(zipfile.ZipFile, "writestr", changed)
    assert (
        build_archive.capture_build(workspace, destination, [{"kind": "build", "exit_code": 0}])["status"]
        == "unavailable"
    )
    assert not destination.exists()


def test_root_rename_during_capture_does_not_publish(tmp_path, monkeypatch):
    workspace, destination = sample(tmp_path)
    original = zipfile.ZipFile.writestr
    changed = False

    def rename(self, *args, **kwargs):
        nonlocal changed
        result = original(self, *args, **kwargs)
        if not changed:
            (workspace / "dist").rename(workspace / "previous")
            (workspace / "dist").mkdir()
            changed = True
        return result

    monkeypatch.setattr(zipfile.ZipFile, "writestr", rename)
    assert (
        build_archive.capture_build(workspace, destination, [{"kind": "build", "exit_code": 0}])["status"]
        == "unavailable"
    )
    assert not destination.exists()
