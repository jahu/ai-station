import importlib.util
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def launcher():
    spec = importlib.util.spec_from_file_location("compatibility_launch", ROOT / "scripts/launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mock_health(monkeypatch, module, payload):
    client_type = httpx.Client
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
            base_url="http://runner",
        ),
    )


@pytest.mark.parametrize("reported", [None, "0" * 64])
def test_healthy_legacy_or_other_native_source_is_not_reused(monkeypatch, reported):
    module = launcher()
    payload = {"status": "ok", "data_dir": "/test/data"}
    if reported is not None:
        payload["source_fingerprint"] = reported
    mock_health(monkeypatch, module, payload)
    with pytest.raises(RuntimeError, match="Host Runner.*source"):
        module.runner_health(
            {"AI_STATION_RUNNER_SOCKET": "/test/runner.sock", "AI_STATION_DATA_HOST_PATH": "/test/data"}
        )


def test_identical_native_source_reuses_runner_and_keeps_data_root_guard(monkeypatch):
    from ai_station_runner.source_identity import SOURCE_FINGERPRINT

    module = launcher()
    mock_health(
        monkeypatch,
        module,
        {"status": "ok", "data_dir": "/test/data", "source_fingerprint": SOURCE_FINGERPRINT},
    )
    env = {"AI_STATION_RUNNER_SOCKET": "/test/runner.sock", "AI_STATION_DATA_HOST_PATH": "/test/data"}
    assert module.runner_health(env)
    with pytest.raises(RuntimeError, match="different data directory"):
        module.runner_health({**env, "AI_STATION_DATA_HOST_PATH": "/other/data"})


@pytest.mark.parametrize("changed_during_build", [False, True])
def test_mismatch_never_starts_processes_even_if_runner_changes_during_build(
    monkeypatch, tmp_path, changed_during_build
):
    import subprocess

    from ai_station_runner.source_identity import SOURCE_FINGERPRINT

    module = launcher()
    env = {"AI_STATION_RUNNER_SOCKET": "/test/runner.sock", "AI_STATION_DATA_HOST_PATH": str(tmp_path)}
    payload = {"status": "ok", "data_dir": str(tmp_path)}
    if changed_during_build:
        payload["source_fingerprint"] = SOURCE_FINGERPRINT
    mock_health(monkeypatch, module, payload)
    calls = []

    def only_compose_inspection(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            assert argv[-3:] == ["ps", "--all", "--quiet"]
        else:
            assert changed_during_build and len(calls) == 2 and argv[:2] == ["docker", "build"]
            payload["source_fingerprint"] = "0" * 64
        return subprocess.CompletedProcess(argv, 0, stdout="")

    def no_process(*args, **kwargs):
        pytest.fail("A source mismatch must not launch, replace or stop a process")

    monkeypatch.setattr(module, "configuration", lambda: env)
    monkeypatch.setattr(module.sys, "argv", ["launch.py"])
    monkeypatch.setattr(module.os, "chdir", lambda path: None)
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    monkeypatch.setattr(module.subprocess, "run", only_compose_inspection)
    monkeypatch.setattr(module.subprocess, "Popen", no_process)
    with pytest.raises(RuntimeError, match="Host Runner.*source"):
        module.main()
    assert len(calls) == (2 if changed_during_build else 1)
