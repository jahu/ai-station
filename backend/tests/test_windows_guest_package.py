"""Windows guest package/bridge boundaries; never import WSL or modify host services."""

import gzip
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import build_windows_guest as builder
import desktop
import pytest

SPEC = importlib.util.spec_from_file_location("wsl_guest_control", builder.SOURCE / "guest_control.py")
guest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guest)


@pytest.mark.parametrize("args", [[], ["shell"], ["start", "echo"], ["stop", "--pid", "1"], ["../start"]])
def test_bridge_has_no_command_path_pid_or_arbitrary_argument_surface(args, monkeypatch):
    check = Mock()
    monkeypatch.setattr(guest, "identity", check)
    with pytest.raises(ValueError, match="only start"):
        guest.main(args)
    check.assert_not_called()


@pytest.mark.parametrize("uid,euid", [(0, 0), (1001, 0), (500, 500)])
def test_bridge_never_runs_the_application_as_root_or_other_system_account(monkeypatch, uid, euid):
    monkeypatch.setattr(guest.os, "getuid", lambda: uid)
    monkeypatch.setattr(guest.os, "geteuid", lambda: euid)
    with pytest.raises(ValueError, match="ordinary"):
        guest.identity()


@pytest.mark.parametrize(
    "name,home", [("root", "/root"), ("ubuntu", "/home/ubuntu"), ("station", "/tmp/station")]
)
def test_bridge_rejects_another_guest_account(monkeypatch, name, home):
    monkeypatch.setattr(guest.os, "getuid", lambda: 1001)
    monkeypatch.setattr(guest.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(guest.pwd, "getpwuid", lambda _: SimpleNamespace(pw_name=name, pw_dir=home))
    with pytest.raises(ValueError, match="dedicated"):
        guest.identity()


def test_ambient_windows_and_other_station_settings_cannot_redirect_the_guest(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://foreign:2375")
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", "/unrelated")
    monkeypatch.setenv("XDG_DATA_HOME", "/another/station")
    monkeypatch.setenv("PYTHONPATH", "/arbitrary/code")
    env = guest.environment()
    assert env["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert env["HOME"] == "/home/station"
    assert not any(k.startswith(("AI_STATION_", "PYTHON")) for k in env)
    assert "XDG_DATA_HOME" not in env and "DISPLAY" not in env and "BROWSER" not in env


@pytest.mark.parametrize(
    "action,options",
    [("start", ["--console", "--background"]), ("status", ["--status"]), ("stop", ["--stop"])],
)
def test_only_the_installed_ordinary_user_launcher_and_fixed_options_are_executed(
    monkeypatch, action, options
):
    monkeypatch.setattr(guest, "identity", lambda: None)
    monkeypatch.setattr(guest, "open_existing", lambda _: False)
    monkeypatch.setattr(guest.os, "environ", {})
    execute = Mock()
    monkeypatch.setattr(guest.os, "execve", execute)
    guest.main([action])
    execute.assert_called_once_with(
        "/usr/lib/ai-station/station", ["/usr/lib/ai-station/station", *options], guest.environment()
    )


def test_open_does_not_create_or_restart_a_stopped_station(monkeypatch):
    monkeypatch.setattr(guest, "identity", lambda: None)
    monkeypatch.setattr(guest, "open_existing", lambda _: False)
    monkeypatch.setattr(guest.os, "environ", {})
    execute = Mock()
    monkeypatch.setattr(guest.os, "execve", execute)
    with pytest.raises(RuntimeError, match="stopped"):
        guest.main(["open"])
    execute.assert_not_called()


def test_private_setup_authority_is_not_read_without_an_actual_live_owner(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(desktop, "state_root", lambda: tmp_path)
    desktop.publish_ready(tmp_path, "http://127.0.0.1:8767/#/?setup_token=" + "a" * 43, instance_id="c" * 32)
    assert not guest.open_existing(desktop)
    (tmp_path / "desktop.lock").touch(mode=0o600)
    assert not guest.open_existing(desktop)
    assert capsys.readouterr().out == ""


def test_live_guest_reopen_transports_validated_setup_url_only_through_private_parent_pipe(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(desktop, "state_root", lambda: tmp_path)
    (tmp_path / "desktop.lock").touch(mode=0o600)
    code = 'import fcntl,sys; f=open(sys.argv[1],"r"); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.read()'
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", code, str(tmp_path / "desktop.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "ready"
        desktop.publish_ready(
            tmp_path, "http://127.0.0.1:8767/#/?setup_token=" + "a" * 43, instance_id="c" * 32
        )
        assert guest.open_existing(desktop)
        output = capsys.readouterr().out
        assert output.startswith(desktop.READY)
        assert json.loads(output[len(desktop.READY) :]) == {
            "url": "http://127.0.0.1:8767/#/setup/models?setup_token=" + "a" * 43,
            "instance_id": "c" * 32,
        }
        assert proc.poll() is None
    finally:
        proc.communicate(timeout=5)


def test_guest_lock_rejects_symlink_and_nonregular_file(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "state_root", lambda: tmp_path)
    target = tmp_path / "external"
    target.write_text("not an owner")
    lock = tmp_path / "desktop.lock"
    lock.symlink_to(target)
    with pytest.raises(OSError):
        guest.open_existing(desktop)
    lock.unlink()
    os.mkfifo(lock, mode=0o600)
    with pytest.raises(ValueError, match="regular"):
        guest.open_existing(desktop)


@pytest.fixture
def fake_build(tmp_path, monkeypatch):
    package = tmp_path / "station.deb"
    package.write_bytes(b"audited private package fixture")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "dpkg-deb":
            return SimpleNamespace(
                stdout="Package: ai-station\nVersion: 0.1.0~preview.42\nArchitecture: amd64\n"
            )
        return SimpleNamespace(returncode=0)

    def output(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[0] == "git":
            return ""
        return "sha256:" + "b" * 64 + "\n"

    monkeypatch.setattr(builder.subprocess, "run", run)
    monkeypatch.setattr(builder.subprocess, "check_output", output)

    class Export:
        def __init__(self, argv, **kwargs):
            calls.append(argv)
            self.stdout = io.BytesIO(b"neutral exported guest fixture")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def wait(self):
            return 0

    monkeypatch.setattr(builder.subprocess, "Popen", Export)
    return package, calls


def test_package_hash_failure_cannot_build_import_or_overwrite_anything(fake_build, tmp_path):
    package, calls = fake_build
    with pytest.raises(ValueError, match="differs"):
        builder.build(package, "0" * 64, tmp_path / "out")
    assert calls == []


def test_existing_installation_is_never_overwritten_by_builder(fake_build, tmp_path):
    package, calls = fake_build
    output = tmp_path / "owned"
    output.mkdir()
    (output / "keep").write_text("private data")
    with pytest.raises(ValueError, match="fresh"):
        builder.build(package, desktop.digest(package), output)
    assert (output / "keep").read_text() == "private data"
    assert not any(command[0] == "docker" for command in calls)


def test_built_guest_has_source_package_and_archive_receipts_and_only_its_stopped_export_is_removed(
    fake_build, tmp_path
):
    package, calls = fake_build
    output = tmp_path / "out"
    result = builder.build(package, desktop.digest(package), output)
    assert result["package_sha256"] == desktop.digest(package)
    assert result["rootfs_sha256"] == desktop.digest(output / "ai-station-wsl-rootfs.tar.gz")
    assert (
        gzip.decompress((output / "ai-station-wsl-rootfs.tar.gz").read_bytes())
        == b"neutral exported guest fixture"
    )
    assert result["source_head"] == "a" * 40
    assert result["base"] == builder.BASE and "@sha256:" in builder.BASE
    assert "pending" in result["qualification"]
    docker = [command for command in calls if command[0] == "docker"]
    assert not any(command[1] in {"start", "run", "import", "prune"} for command in docker)
    create = next(command for command in docker if command[1] == "create")
    assert create[-1] == result["image_id"]
    assert docker[-1] == ["docker", "rm", create[3]]


def test_wsl_guest_configuration_does_not_mount_windows_drives_or_enable_interop():
    import configparser

    config = configparser.ConfigParser()
    config.read(builder.SOURCE / "wsl.conf")
    assert config["boot"].getboolean("systemd")
    assert config["user"]["default"] == "station"
    assert not config["automount"].getboolean("enabled")
    assert not config["automount"].getboolean("mountFsTab")
    assert not config["interop"].getboolean("enabled")
    assert not config["interop"].getboolean("appendWindowsPath")


def test_failed_export_removes_only_its_stopped_container_and_never_publishes(
    fake_build, tmp_path, monkeypatch
):
    package, calls = fake_build

    class FailedExport:
        def __init__(self, argv, **kwargs):
            self.stdout = io.BytesIO(b"incomplete archive")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def wait(self):
            return 1

    monkeypatch.setattr(builder.subprocess, "Popen", FailedExport)
    output = tmp_path / "incomplete"
    with pytest.raises(RuntimeError, match="did not complete"):
        builder.build(package, desktop.digest(package), output)
    assert not output.exists()
    assert calls[-1][0:2] == ["docker", "rm"]
    assert calls[-1][2].startswith("ai-station-wsl-export-")
    assert not list(tmp_path.glob(".wsl-build-*"))


@pytest.mark.parametrize(
    "fields",
    [
        "Package: unrelated\nVersion: 1\nArchitecture: amd64\n",
        "Package: ai-station\nVersion: 1\nArchitecture: arm64\n",
    ],
)
def test_guest_builder_rejects_unrelated_package_or_wrong_cpu_architecture(fake_build, monkeypatch, fields):
    package, calls = fake_build
    run = Mock(return_value=SimpleNamespace(stdout=fields))
    monkeypatch.setattr(builder.subprocess, "run", run)
    with pytest.raises(ValueError, match="amd64 package"):
        builder.package_identity(package, desktop.digest(package))
    run.assert_called_once()
    assert not calls


def test_changed_package_during_staging_cannot_build_under_an_earlier_hash(fake_build, tmp_path, monkeypatch):
    package, calls = fake_build
    original = builder.shutil.copy2

    def tamper(source, target):
        result = original(source, target)
        if Path(target).name == "station.deb":
            Path(target).write_bytes(b"changed during copy")
        return result

    monkeypatch.setattr(builder.shutil, "copy2", tamper)
    with pytest.raises(ValueError, match="changed while"):
        builder.build(package, desktop.digest(package), tmp_path / "out")
    assert not any(command[0] == "docker" for command in calls)
    assert not (tmp_path / "out").exists()
    assert package.read_bytes() == b"audited private package fixture"
