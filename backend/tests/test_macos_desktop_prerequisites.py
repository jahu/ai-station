"""Mac package preflight uses only fixed read-only local-engine operations."""

import json

import desktop
import desktop_engine
import macos_desktop_docker as preflight
import pytest
from test_desktop_versions import PACKAGE


@pytest.fixture
def candidate(monkeypatch):
    monkeypatch.setattr(preflight.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(preflight.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(preflight.platform, "mac_ver", lambda: ("15.7.9", (), ""))
    package = PACKAGE | {
        "platform": "Darwin",
        "architecture": "x86_64",
        "minimum_os": "13.3",
        "desktop_protocol": desktop.DESKTOP_PROTOCOL,
    }
    engine = desktop_engine.DockerEngine(
        ("/Applications/Docker.app/Contents/Resources/bin/docker", "--host", "unix:///private/local.sock"),
        {"HOME": "/Users/neutral"},
    )
    calls, replies = (
        [],
        [
            (0, "2.39.1-desktop.1"),
            (0, json.dumps({"os": "linux", "arch": "amd64", "system": "Docker Desktop"})),
        ],
    )
    monkeypatch.setattr(desktop_engine, "select", lambda _: engine)

    def read_only(argv, **kwargs):
        calls.append((argv, kwargs))
        return replies.pop(0)

    monkeypatch.setattr(desktop_engine, "context_command", read_only)
    return package, engine, calls, replies


def test_native_package_checks_only_its_pinned_compose_and_engine(candidate):
    package, engine, calls, _ = candidate
    assert preflight.prerequisites(package, {}) == engine
    assert calls[0][0] == engine.command("compose", "version", "--short")
    assert calls[1][0][:5] == engine.command("info", "--format")
    assert all(kwargs["env"] == engine.environment for _, kwargs in calls)


@pytest.mark.parametrize(
    "observed",
    [
        {"os": "darwin", "arch": "amd64", "system": "Docker Desktop"},
        {"os": "linux", "arch": "arm64", "system": "Docker Desktop"},
        {"os": "linux", "arch": "amd64", "system": "unknown"},
        {"os": "linux", "arch": "amd64", "system": "Docker Desktop", "extra": "PRIVATE_FIXTURE"},
    ],
)
def test_foreign_or_mismatched_engine_never_admits_the_package(candidate, observed):
    package, _, _, replies = candidate
    replies[1] = (0, json.dumps(observed))
    with pytest.raises(RuntimeError, match="matching local Linux engine") as error:
        preflight.prerequisites(package, {})
    assert "PRIVATE_FIXTURE" not in str(error.value)


def test_unavailable_compose_stops_before_engine_or_workload_operations(candidate):
    package, _, calls, replies = candidate
    replies[0] = (1, "")
    with pytest.raises(RuntimeError, match="Compose is unavailable"):
        preflight.prerequisites(package, {})
    assert len(calls) == 1


def test_unsupported_host_is_refused_before_docker_selection(candidate, monkeypatch):
    package, _, calls, _ = candidate
    monkeypatch.setattr(preflight.platform, "mac_ver", lambda: ("12.0", (), ""))
    with pytest.raises(ValueError, match="incompatible"):
        preflight.prerequisites(package, {})
    assert calls == []


def test_desktop_routes_mac_package_through_native_preflight(candidate, monkeypatch):
    package, _, calls, _ = candidate
    monkeypatch.setattr(desktop, "manifest", lambda _: package)
    desktop.prerequisites()
    assert len(calls) == 2
