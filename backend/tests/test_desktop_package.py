"""Desktop package ownership, source integrity and existing supervisor boundaries."""

import io
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import desktop
import pytest
from dotenv import dotenv_values


def fixture_bundle(folder):
    folder.mkdir()
    (folder / "station").write_text("neutral test package")
    value = {
        "schema": 1,
        "bundle_id": "a" * 64,
        "image_id": "sha256:" + "b" * 64,
        "image_tag": "ai-station:desktop-" + "a" * 16,
        "files": {"station": desktop.digest(folder / "station")},
    }
    (folder / "desktop-manifest.json").write_text(json.dumps(value))
    return value


def test_verified_version_copy_never_replaces_existing_application_or_user_data(tmp_path):
    source, state = tmp_path / "package", tmp_path / "owned"
    value = fixture_bundle(source)
    state.mkdir()
    (state / "data").mkdir()
    (state / "data/keep.txt").write_text("existing private data")
    installed = desktop.install_copy(state, source, value)
    assert installed != source and installed.parent.name == "releases"
    assert desktop.install_copy(state, source, value) == installed
    (source / "station").write_text("tampered update")
    with pytest.raises(ValueError, match="changed"):
        desktop.verify(source, value)
    assert (installed / "station").read_text() == "neutral test package"
    assert (state / "data/keep.txt").read_text() == "existing private data"


@pytest.mark.parametrize("name", ["../external", "/tmp/external", "nested/../../external", "a\\b"])
def test_package_manifest_rejects_nonrelative_file_coordinates(tmp_path, name):
    source = tmp_path / "package"
    value = fixture_bundle(source)
    value["files"] = {name: "a" * 64}
    (source / "desktop-manifest.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        desktop.manifest(source)


def test_package_link_cannot_escape_its_bundle(tmp_path):
    source = tmp_path / "package"
    value = fixture_bundle(source)
    external = tmp_path / "outside"
    external.write_text("private")
    (source / "station").unlink()
    (source / "station").symlink_to(external)
    with pytest.raises(ValueError):
        desktop.manifest(source)
    with pytest.raises(ValueError):
        desktop.install_copy(source / "data", source, value)


def test_new_desktop_configuration_uses_private_accounts_and_preserves_existing_settings(tmp_path):
    root = tmp_path / "dane Łódź"
    root.mkdir()
    path = desktop.configuration(root)
    config = dotenv_values(path)
    assert config["AI_STATION_ACCESS_PROFILE"] == "accounts"
    assert Path(config["AI_STATION_DATA_HOST_PATH"]) == root / "data"
    assert config["COMPOSE_PROJECT_NAME"].startswith("ai-station-desktop-")
    path.write_text(path.read_text() + "AI_STATION_WORKER_SLOTS=1\n")
    before = path.read_bytes()
    assert desktop.configuration(root) == path
    assert path.read_bytes() == before


def test_occupied_default_port_is_not_reused_or_shutdown():
    with socket.socket() as occupied:
        try:
            occupied.bind(("127.0.0.1", 8765))
        except OSError:
            pass  # The running developer workstation already owns it.
        assert 8766 <= desktop.free_port() <= 8864


def test_unmarked_existing_station_is_never_silently_migrated_to_accounts(tmp_path):
    root = tmp_path / "unmarked-station"
    database = root / "data/db/ai-station.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"existing operator database")
    with pytest.raises(ValueError, match="not adopted"):
        desktop.configuration(root)
    assert database.read_bytes() == b"existing operator database"
    assert not (root / "desktop.env").exists()


def test_other_station_and_python_environment_cannot_redirect_desktop_launch(monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", "/unrelated/station")
    monkeypatch.setenv("AI_STATION_LAN_HOST", "192.168.1.7")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "unrelated")
    monkeypatch.setenv("PYTHONPATH", "/unrelated/modules")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = desktop.launch_environment()
    assert not any(key.startswith(("AI_STATION_", "COMPOSE_", "PYTHON")) for key in env)
    assert env["PATH"] == "/usr/bin"


def test_matching_existing_image_is_reused_and_mismatched_tag_is_not_overwritten(tmp_path, monkeypatch):
    value = fixture_bundle(tmp_path / "package")
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=value["image_id"] + "\n"))
    monkeypatch.setattr(desktop.subprocess, "run", run)
    desktop.import_image(tmp_path / "package", value, io.StringIO())
    assert run.call_count == 1
    assert run.call_args.args[0][:3] == ["docker", "image", "inspect"]
    run.return_value.stdout = "sha256:" + "c" * 64
    with pytest.raises(ValueError, match="not overwritten"):
        desktop.import_image(tmp_path / "package", value, io.StringIO())
    assert run.call_count == 2


@pytest.mark.parametrize("system,flags", [("Linux", "-I"), ("Darwin", "-IB")])
def test_private_setup_link_is_consumed_without_ordinary_log_persistence(
    tmp_path, monkeypatch, system, flags
):
    monkeypatch.setattr(desktop.platform, "system", lambda: system)
    proof = "http://127.0.0.1:8766/#/?setup_token=" + "a" * 43
    proc = Mock()
    proc.stdout = io.StringIO(
        "starting\n" + desktop.READY + json.dumps({"url": proof, "instance_id": "d" * 32}) + "\n"
    )
    proc.poll.return_value = None
    spawn = Mock(return_value=proc)
    monkeypatch.setattr(desktop.subprocess, "Popen", spawn)
    browser = Mock()
    monkeypatch.setattr(desktop.webbrowser, "open", browser)
    monkeypatch.setattr(desktop, "running_window", lambda *args, **kwargs: "stop")
    log = io.StringIO()
    desktop.supervise(
        tmp_path,
        tmp_path / "desktop.env",
        {"image_tag": "ai-station:desktop-test"},
        log,
        instance_id="d" * 32,
    )
    browser.assert_called_once_with(proof.replace("/#/?", "/#/setup/models?"))
    assert log.getvalue() == "starting\n" and "setup_token" not in log.getvalue()
    command = spawn.call_args.args[0]
    assert command[:3] == [str(tmp_path / "python/bin/python3"), flags, str(tmp_path / "scripts/launch.py")]
    assert "--config" in command and "--no-build" in command and "--desktop" in command
    assert spawn.call_args.kwargs["start_new_session"] is True
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=45)


def test_unreachable_owned_supervisor_is_not_replaced_or_killed_indiscriminately():
    import subprocess

    proc = Mock()
    proc.poll.return_value = None
    proc.wait.side_effect = subprocess.TimeoutExpired("owned", 45)
    with pytest.raises(RuntimeError, match="still stopping"):
        desktop.stop(proc)
    proc.terminate.assert_called_once()
    proc.kill.assert_not_called()


def test_xdg_root_and_configuration_symlinks_do_not_write_outside_owned_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    external = tmp_path / "external"
    external.mkdir()
    (tmp_path / "ai-station-desktop").symlink_to(external)
    with pytest.raises(ValueError):
        desktop.state_root()
    root = tmp_path / "owned"
    root.mkdir()
    (root / "desktop.env").symlink_to(external / "config")
    with pytest.raises(ValueError):
        desktop.configuration(root)
    assert list(external.iterdir()) == []


def test_state_root_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    before = os.umask(0o077)
    try:
        root = desktop.state_root()
    finally:
        os.umask(before)
    assert root.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://user@127.0.0.1:8765",
        "http://127.0.0.1:8765/?token=secret",
        "http://127.0.0.1:8765/#/external",
    ],
)
def test_desktop_never_opens_unexpected_ready_addresses(url):
    with pytest.raises(ValueError):
        desktop.browser_url(url)


def test_desktop_rejects_remote_docker_before_importing_any_image(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://192.0.2.1:2375")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(desktop.shutil, "which", lambda _: "/usr/bin/docker")
    execute = Mock(side_effect=AssertionError("Must not contact a remote daemon"))
    monkeypatch.setattr(desktop.subprocess, "run", execute)
    with pytest.raises(RuntimeError, match="local Docker"):
        desktop.prerequisites()
    execute.assert_not_called()
