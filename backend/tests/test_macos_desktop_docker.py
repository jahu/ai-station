"""Finder discovery and routing policy, without executing Docker or Mac code."""

import os

import macos_desktop_docker as desktop
import pytest


@pytest.fixture
def installed(tmp_path, monkeypatch):
    home = tmp_path / "user"
    binary = tmp_path / "Applications/Docker.app/Contents/Resources/bin/docker"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"neutral executable fixture, never run")
    binary.chmod(0o755)
    home.mkdir()
    monkeypatch.setattr(desktop.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(desktop, "application_binaries", lambda: (binary,))
    monkeypatch.setattr(desktop.Path, "home", lambda: home)
    monkeypatch.setattr(desktop.shutil, "which", lambda _: None)
    return binary, home


def test_finder_finds_installed_application_without_shell_path(installed):
    binary, _ = installed
    assert desktop.find_cli() == binary


def test_unrelated_path_executable_is_never_selected(installed, tmp_path, monkeypatch):
    binary, _ = installed
    binary.unlink()
    outside = tmp_path / "other-docker"
    outside.write_text("unrelated executable")
    outside.chmod(0o755)
    monkeypatch.setattr(desktop.shutil, "which", lambda _: str(outside))
    with pytest.raises(RuntimeError, match="Open Docker Desktop"):
        desktop.find_cli()
    assert outside.read_text() == "unrelated executable"


def test_cli_symlink_escape_is_rejected_without_changing_target(installed, tmp_path):
    binary, _ = installed
    binary.unlink()
    outside = tmp_path / "outside"
    outside.write_text("external fixture")
    outside.chmod(0o755)
    binary.symlink_to(outside)
    with pytest.raises(RuntimeError, match="Open Docker Desktop"):
        desktop.find_cli()
    assert outside.read_text() == "external fixture"


def test_shared_writable_binary_is_not_silently_repaired(installed):
    binary, _ = installed
    binary.chmod(0o777)
    with pytest.raises(RuntimeError, match="Open Docker Desktop"):
        desktop.find_cli()
    assert binary.stat().st_mode & 0o777 == 0o777


def test_context_is_fixed_and_other_station_credentials_or_routing_are_not_inherited(installed, monkeypatch):
    binary, home = installed
    for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_CONFIG", "AI_STATION_LLM_API_KEY", "GITHUB_TOKEN"):
        monkeypatch.setenv(key, "PRIVATE_FIXTURE")
    calls = []

    def command(argv, *, env):
        calls.append((argv, env))
        return 0, "unix:///Users/neutral/.docker/run/docker.sock"

    assert desktop.connection(command) == (str(binary), "unix:///Users/neutral/.docker/run/docker.sock")
    argv, env = calls[0]
    assert argv[:4] == [str(binary), "context", "inspect", "desktop-linux"]
    assert env == {"HOME": str(home), "LANG": "C", "PATH": str(binary.parent) + os.pathsep + os.defpath}


@pytest.mark.parametrize(
    "endpoint",
    [
        "tcp://example.invalid:2375",
        "ssh://example.invalid",
        "unix://host/path",
        "unix:relative",
        "unix:///path?query",
        "unix:///path#fragment",
        "unix:///path\n",
    ],
)
def test_non_local_or_ambiguous_context_never_reaches_engine_operations(installed, endpoint):
    with pytest.raises(ValueError, match="local Docker Desktop Unix"):
        desktop.connection(lambda *a, **k: (0, endpoint))


def test_non_mac_discovery_refuses_before_any_process(monkeypatch):
    monkeypatch.setattr(desktop.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        desktop.shutil, "which", lambda _: pytest.fail("Inspected executables on another platform")
    )
    with pytest.raises(RuntimeError, match="native Mac"):
        desktop.find_cli()
