"""Mac storage namespace and Linux compatibility, with disposable filesystem roots."""

import json
import os
import stat
from pathlib import Path

import desktop
import pytest
from dotenv import dotenv_values


@pytest.fixture
def native(tmp_path, monkeypatch):
    parent = tmp_path / "runtime-parent"
    parent.mkdir(mode=0o700)
    home = tmp_path / ("long-user-home-" + "a" * 80)
    home.mkdir()
    monkeypatch.setattr(desktop.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(desktop.Path, "home", lambda: home)
    monkeypatch.setattr(desktop, "DARWIN_RUNTIME_PARENT", parent)
    monkeypatch.setattr(desktop, "free_port", lambda: 8765)
    return desktop.state_root(), parent


def test_native_state_root_and_short_control_are_separate_from_runner_mount(native):
    root, parent = native
    assert root.parts[-3:] == ("Library", "Application Support", "AI Station")
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    private = desktop.control_directory(root)
    assert private.parent == parent and stat.S_IMODE(private.stat().st_mode) == 0o700
    marker = private / "desktop-owner.json"
    assert marker.stat().st_nlink == 1 and stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert json.loads(marker.read_text())["uid"] == os.getuid()
    assert desktop.control_directory(root) == private
    config = desktop.configuration(root)
    values = dotenv_values(config)
    runner_socket = Path(values["AI_STATION_RUNNER_SOCKET"])
    assert runner_socket == private / "runner/runner.sock"
    assert not (private / "desktop-control.sock").is_relative_to(runner_socket.parent)
    assert values["AI_STATION_DATA_HOST_PATH"] == str(root / "data")
    before = config.read_bytes()
    assert desktop.configuration(root).read_bytes() == before


@pytest.mark.parametrize("field,value", [("uid", -1), ("desktop_root_sha256", "0" * 64), ("schema", 2)])
def test_marker_mismatch_is_not_adopted_or_overwritten(native, field, value):
    root, _ = native
    private = desktop.control_directory(root)
    marker = private / "desktop-owner.json"
    payload = json.loads(marker.read_text())
    payload[field] = value
    marker.write_text(json.dumps(payload))
    before = marker.read_bytes()
    with pytest.raises(ValueError, match="another installation"):
        desktop.control_directory(root)
    assert marker.read_bytes() == before


@pytest.mark.parametrize("mode", [0o755, 0o777, 0o750])
def test_shared_runtime_directory_is_refused_without_chmod_or_cleanup(native, mode):
    root, _ = native
    private = desktop.control_directory(root)
    private.chmod(mode)
    with pytest.raises(ValueError, match="private owned"):
        desktop.control_directory(root)
    assert stat.S_IMODE(private.stat().st_mode) == mode


def test_directory_or_marker_symlink_cannot_redirect_storage(native, tmp_path):
    root, _ = native
    private = desktop.control_directory(root)
    marker = private / "desktop-owner.json"
    before = marker.read_bytes()
    marker.unlink()
    outside = tmp_path / "outside-marker"
    outside.write_bytes(before)
    marker.symlink_to(outside)
    with pytest.raises(OSError):
        desktop.control_directory(root)
    assert outside.read_bytes() == before
    marker.unlink()
    private.rmdir()
    outside_dir = tmp_path / "outside-directory"
    outside_dir.mkdir()
    private.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="private owned"):
        desktop.control_directory(root)
    assert not list(outside_dir.iterdir())


def test_missing_marker_does_not_claim_unknown_contents(native):
    root, _ = native
    private = desktop.control_directory(root)
    (private / "desktop-owner.json").unlink()
    item = private / "keep.txt"
    item.write_text("preexisting private content")
    with pytest.raises(ValueError, match="unrecognized"):
        desktop.control_directory(root)
    assert item.read_text() == "preexisting private content"


def test_two_desktop_roots_do_not_share_control_or_runner_sockets(native):
    root, _ = native
    other = root.parent / "other-station"
    other.mkdir(mode=0o700)
    assert desktop.control_directory(root) != desktop.control_directory(other)


def test_linux_retains_existing_xdg_root_configuration_and_control_path(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(desktop, "free_port", lambda: 8765)
    root = desktop.state_root()
    assert root == tmp_path / "xdg/ai-station-desktop"
    assert desktop.control_directory(root) == root
    values = dotenv_values(desktop.configuration(root))
    assert "AI_STATION_RUNNER_SOCKET" not in values
    assert values["AI_STATION_ACCESS_PROFILE"] == "accounts"
