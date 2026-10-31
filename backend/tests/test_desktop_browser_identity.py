"""Bind first-admin/browser handoffs to the actual owned desktop service."""

import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import desktop
import httpx
import pytest
from app.api import app
from app.config import Settings, get_settings
from fastapi.testclient import TestClient
from launch import local_entry_url
from pydantic import ValidationError


@pytest.mark.parametrize("bad", ["short", "A" * 32, "../" + "a" * 32, "a" * 33, "a" * 31 + "\n"])
def test_desktop_environment_identity_rejects_unbounded_or_noncanonical_inputs(bad):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, desktop_instance_id=bad)


def test_public_health_identifies_a_desktop_without_exposing_setup_authority(monkeypatch):
    monkeypatch.setenv("AI_STATION_DESKTOP_INSTANCE_ID", "a" * 32)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.headers["cache-control"] == "no-store"
            value = response.json()
            assert value == {"status": "ok", "version": "0.1.0", "desktop_instance_id": "a" * 32}
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "ok"},
        {"status": "ok", "desktop_instance_id": "b" * 32},
        [],
        {"status": "failed", "desktop_instance_id": "a" * 32},
    ],
)
def test_wrong_local_listener_cannot_cause_first_admin_proof_disclosure(body):
    requests = []
    run = Mock()

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(RuntimeError, match="different local service"):
            local_entry_url(
                client, run, "http://127.0.0.1:8766", "http://127.0.0.1:8766", instance_id="a" * 32
            )
    assert requests == ["http://127.0.0.1:8766/api/health"]
    run.assert_not_called()


def test_matched_desktop_obtains_bootstrap_only_after_identity_check():
    calls = []
    proof = "http://127.0.0.1:8766/#/?setup_token=" + "z" * 43

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={"status": "ok", "desktop_instance_id": "a" * 32}
            if request.url.path.endswith("/health")
            else {"setup_required": True},
        )

    run = Mock(return_value=SimpleNamespace(stdout=proof + "\n"))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert (
            local_entry_url(
                client, run, "http://127.0.0.1:8766", "http://127.0.0.1:8766", instance_id="a" * 32
            )
            == proof
        )
    assert calls == ["/api/health", "/api/auth"]
    run.assert_called_once()


def test_readiness_persistence_retains_identity_and_rejects_corruption(tmp_path):
    desktop.publish_ready(tmp_path, "http://127.0.0.1:8766", instance_id="a" * 32)
    assert desktop.ready_info(tmp_path) == {"url": "http://127.0.0.1:8766", "instance_id": "a" * 32}
    assert desktop.ready_url(tmp_path) == "http://127.0.0.1:8766"
    path = tmp_path / desktop.READY_FILE
    for bad in [None, True, 42, "wrong", "A" * 32]:
        path.write_text(json.dumps({"url": "http://127.0.0.1:8766", "instance_id": bad}))
        path.chmod(0o600)
        with pytest.raises(ValueError, match="identity"):
            desktop.ready_info(tmp_path)


def test_owned_child_and_private_parent_pipe_use_the_same_identity_without_log_disclosure(
    tmp_path, monkeypatch, capsys
):
    url = "http://127.0.0.1:8766/#/?setup_token=" + "z" * 43
    proc = Mock()
    proc.stdout = io.StringIO(desktop.READY + json.dumps({"url": url, "instance_id": "a" * 32}) + "\n")
    alive = {"value": True}
    proc.poll.side_effect = lambda: None if alive["value"] else 0
    proc.terminate.side_effect = lambda: alive.update(value=False)
    spawn = Mock(return_value=proc)
    monkeypatch.setattr(desktop.subprocess, "Popen", spawn)
    control = SimpleNamespace(
        ready=threading.Event(), background=threading.Event(), stop_requested=threading.Event()
    )
    log = io.StringIO()
    captured = {}

    def ready(value):
        captured["url"] = value
        control.stop_requested.set()

    desktop.supervise(
        tmp_path,
        tmp_path / "config",
        {"image_tag": "owned"},
        log,
        console=True,
        control=control,
        on_ready_url=ready,
        instance_id="a" * 32,
    )
    frame = json.loads(capsys.readouterr().out[len(desktop.READY) :])
    assert frame == {"url": desktop.browser_url(url), "instance_id": "a" * 32}
    assert spawn.call_args.kwargs["env"]["AI_STATION_DESKTOP_INSTANCE_ID"] == "a" * 32
    assert log.getvalue() == "" and captured["url"] == desktop.browser_url(url)
    proc.terminate.assert_called_once()


@pytest.mark.parametrize("identity", [None, "b" * 32])
def test_child_without_matching_identity_never_opens_or_publishes_its_setup_url(
    tmp_path, monkeypatch, identity
):
    frame = {"url": "http://127.0.0.1:8766/#/?setup_token=" + "z" * 43}
    if identity is not None:
        frame["instance_id"] = identity
    proc = Mock()
    proc.stdout = io.StringIO(desktop.READY + json.dumps(frame) + "\n")
    proc.poll.return_value = None
    monkeypatch.setattr(desktop.subprocess, "Popen", Mock(return_value=proc))
    browser = Mock()
    publish = Mock()
    monkeypatch.setattr(desktop.webbrowser, "open", browser)
    log = io.StringIO()
    with pytest.raises(RuntimeError, match="could not start"):
        desktop.supervise(
            tmp_path,
            tmp_path / "config",
            {"image_tag": "owned"},
            log,
            on_ready_url=publish,
            instance_id="a" * 32,
        )
    browser.assert_not_called()
    publish.assert_not_called()
    assert log.getvalue() == ""
    proc.terminate.assert_called_once()


def test_non_json_listener_is_rejected_before_requesting_setup_authority():
    run = Mock()
    paths = []

    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(200, text="A different local application")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(RuntimeError, match="unexpected local response"):
            local_entry_url(
                client, run, "http://127.0.0.1:8766", "http://127.0.0.1:8766", instance_id="a" * 32
            )
    assert paths == ["/api/health"]
    run.assert_not_called()


@pytest.mark.parametrize("port", [0, 80, 8865, 65535, True, "8766"])
def test_invalid_host_port_cannot_start_a_desktop_child(tmp_path, monkeypatch, port):
    spawn = Mock()
    monkeypatch.setattr(desktop.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="port"):
        desktop.supervise(
            tmp_path, tmp_path / "config", {"image_tag": "owned"}, io.StringIO(), host_port=port
        )
    spawn.assert_not_called()


def test_host_selected_port_overrides_only_the_owned_child_environment(tmp_path, monkeypatch):
    proc = Mock()
    proc.stdout = io.StringIO()
    proc.poll.return_value = None
    spawn = Mock(return_value=proc)
    monkeypatch.setattr(desktop.subprocess, "Popen", spawn)
    monkeypatch.setenv("AI_STATION_PORT", "9999")
    config = tmp_path / "config"
    config.write_text("AI_STATION_PORT=8765\n")
    with pytest.raises(RuntimeError, match="could not start"):
        desktop.supervise(tmp_path, config, {"image_tag": "owned"}, io.StringIO(), host_port=8789)
    assert spawn.call_args.kwargs["env"]["AI_STATION_PORT"] == "8789"
    assert config.read_text() == "AI_STATION_PORT=8765\n"
    proc.terminate.assert_called_once()


def test_lost_desktop_owner_does_not_hide_a_live_supervisor(tmp_path, monkeypatch, capsys):
    import sys

    from test_desktop_package import fixture_bundle
    from test_desktop_reopen import live_owner

    package = tmp_path / "package"
    fixture_bundle(package)
    root = tmp_path / "state"
    runtime = root / "data/runtime"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(desktop, "ROOT", package)
    monkeypatch.setattr(desktop, "state_root", lambda: root)
    monkeypatch.setattr(desktop.signal, "signal", lambda *args: None)
    # Independent actual OS-held launcher lock; no Docker or signals to that owner.
    with live_owner(runtime) as owner:
        (runtime / "desktop.lock").rename(runtime / "launcher.lock")
        for action in ["--status", "--stop"]:
            monkeypatch.setattr(sys, "argv", ["desktop.py", action])
            desktop.main()
            assert json.loads(capsys.readouterr().out) == {"running": True, "inspection_required": True}
            assert owner.poll() is None
    assert desktop.unowned_supervisor_active(root) is False
