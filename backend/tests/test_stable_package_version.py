"""Stable package provenance and actual Debian ordering; no OS installation."""

import json
import shutil
import subprocess
from unittest.mock import Mock

import build_linux_package as builder
import pytest


@pytest.fixture
def source(tmp_path, monkeypatch):
    for part in ("backend", "host-runner"):
        folder = tmp_path / part
        folder.mkdir()
        (folder / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.1.0"\n')
        package = folder / ("app" if part == "backend" else "ai_station_runner")
        package.mkdir()
        (package / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/package.json").write_text(json.dumps({"version": "0.1.0"}))
    commands = [
        ("init", "--quiet"),
        ("config", "user.name", "QA Fixture"),
        ("config", "user.email", "qa@example.invalid"),
        ("add", "."),
        ("commit", "--quiet", "-m", "Synthetic versions"),
    ]
    for args in commands:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True)
    head = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    return tmp_path, head


@pytest.mark.parametrize(
    "value", ["", "v0.1.0", "0.1", "0.1.0-rc1", "0.01.0", "0.1.0+local", "65536.1.0", "1.2.3\n", True, None]
)
def test_release_version_rejects_ambiguous_or_unbounded_inputs(value):
    with pytest.raises(ValueError, match="numeric"):
        builder.release_number(value)


def test_stable_metadata_requires_clean_identified_source_and_preserves_preview_default(source):
    _, head = source
    metadata = {"source_epoch": 1793730000, "bundle_id": "f" * 64, "source_head": head, "source_dirty": False}
    assert builder.debian_version(metadata) == "0.1.0~preview.1793730000+ffffffffffffffff"
    assert builder.debian_version({**metadata, "release_version": "0.1.0"}) == "0.1.0"
    for patch in (
        {"source_dirty": True},
        {"source_dirty": 0},
        {"source_head": "missing"},
        {"source_head": None},
    ):
        with pytest.raises(ValueError, match="identified clean"):
            builder.debian_version({**metadata, "release_version": "0.1.0", **patch})


@pytest.mark.parametrize("change", ["file", "untracked", "head", "version"])
def test_stable_source_refuses_changed_or_inconsistent_publisher_state(source, change):
    root, head = source
    builder.release_source("0.1.0", head)
    if change == "file":
        (root / "backend/pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
    elif change == "untracked":
        (root / "unexpected.txt").write_text("changed")
    elif change == "head":
        head = "0" * 40
    else:
        (root / "frontend/package.json").write_text(json.dumps({"version": "0.0.2"}))
    with pytest.raises(ValueError, match="clean reviewed|Align"):
        builder.release_source("0.1.0", head)


def test_invalid_stable_build_refuses_before_download_or_process_dispatch(source, monkeypatch):
    root, _ = source
    acquire, dispatch = Mock(), Mock()
    monkeypatch.setattr(builder, "python_archive", acquire)
    monkeypatch.setattr(builder, "run", dispatch)
    with pytest.raises(ValueError, match="allow-dirty"):
        builder.build(root / "output", release_version="0.1.0", allow_dirty=True)
    with pytest.raises(ValueError, match="Align"):
        builder.build(root / "output", release_version="0.1.1")
    acquire.assert_not_called()
    dispatch.assert_not_called()
    assert not (root / "output").exists()


@pytest.mark.parametrize("change", ["backend", "runner", "dynamic", "duplicate"])
def test_stable_package_rejects_clean_but_inconsistent_runtime_versions(source, change):
    root, _ = source
    name = "host-runner/ai_station_runner/__init__.py" if change == "runner" else "backend/app/__init__.py"
    marker = root / "must-not-execute"
    contents = {
        "dynamic": f'__version__ = __import__("pathlib").Path({str(marker)!r}).touch()\n',
        "duplicate": '__version__ = "0.1.0"\n__version__ = "0.0.1"\n',
    }.get(change, '__version__ = "0.0.1"\n')
    (root / name).write_text(contents)
    subprocess.run(["git", "-C", str(root), "commit", "-am", "Inconsistent runtime", "--quiet"], check=True)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    with pytest.raises(ValueError, match="Align"):
        builder.release_source("0.1.0", head)
    assert not marker.exists()


@pytest.mark.skipif(not shutil.which("dpkg"), reason="Actual Debian version ordering requires dpkg")
def test_stable_promotes_preview_and_supports_later_patch_without_a_forced_downgrade(source):
    _, head = source

    def version(number):
        return builder.debian_version({"release_version": number, "source_head": head, "source_dirty": False})

    for earlier in ("0.0.2", "0.1.0~dev.ffffffffffffffff", "0.1.0~preview.9999999999+ffffffffffffffff"):
        subprocess.run(["dpkg", "--compare-versions", earlier, "lt", version("0.1.0")], check=True)
    subprocess.run(["dpkg", "--compare-versions", version("0.1.0"), "lt", version("0.1.1")], check=True)
