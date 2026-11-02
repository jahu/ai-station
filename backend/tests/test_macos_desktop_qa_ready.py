"""Fresh Desktop GUI/context/daemon races; no real Mac, Docker or installation."""

import json
import subprocess
from pathlib import Path

import macos_desktop_docker as discovery
import macos_desktop_qa_ready as ready
import pytest


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(ready.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ready.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(ready.os, "geteuid", lambda: 501)
    monkeypatch.setattr(discovery, "find_cli", lambda: Path("/Applications/Docker.app/bin/docker"))
    clock = [0.0]
    monkeypatch.setattr(ready.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ready.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return clock


def test_gui_success_waits_for_both_context_and_daemon_and_pins_local_connection(host, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://unrelated.invalid:2375")
    monkeypatch.setenv("GITHUB_TOKEN", "PRIVATE_FIXTURE_TOKEN")
    calls = []
    context = "unix:///Users/qa/.docker/run/docker.sock"

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["check"] is False and 0 < kwargs["timeout"] <= 5
        assert not {"DOCKER_HOST", "GITHUB_TOKEN"} & kwargs["env"].keys()
        if "context" in argv:
            return (1, "not created") if len(calls) == 1 else (0, context)
        assert argv[1:3] == ["--host", context]
        if len(calls) == 3:
            return 1, "daemon starting"
        return 0, json.dumps({"os": "linux", "arch": "x86_64", "system": "Docker Desktop"})

    monkeypatch.setattr(ready, "command", run)
    assert ready.wait_for_engine(timeout=8)["engine_ready"] is True
    assert len(calls) == 4 and host[0] == 2


def test_daemon_timeout_does_not_restart_or_dispatch_workloads(host, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(ready, "command", run)
    with pytest.raises(RuntimeError, match="did not become ready"):
        ready.wait_for_engine(timeout=3)
    assert host[0] == 3 and all(argv[1:4] == ["context", "inspect", "desktop-linux"] for argv in calls)


def test_remote_context_is_rejected_before_any_engine_request(host, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return 0, "tcp://unrelated.invalid:2375"

    monkeypatch.setattr(ready, "command", run)
    with pytest.raises(ValueError, match="local Docker Desktop Unix"):
        ready.wait_for_engine()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "value",
    [
        {"os": "linux", "arch": "arm64", "system": "Docker Desktop"},
        {"os": "linux", "arch": "amd64", "system": "Other engine"},
        {"os": "windows", "arch": "amd64", "system": "Docker Desktop"},
    ],
)
def test_ready_but_wrong_engine_is_not_silently_accepted(host, monkeypatch, value):
    def run(argv, **kwargs):
        if "context" in argv:
            return 0, "unix:///Users/qa/.docker/run/docker.sock"
        return 0, json.dumps(value)

    monkeypatch.setattr(ready, "command", run)
    with pytest.raises(ValueError, match="expected local Intel Docker Desktop"):
        ready.wait_for_engine()
