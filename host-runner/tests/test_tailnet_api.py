"""Typed native API over a fixture-owned daemon; no external enrollment."""

from uuid import uuid4

import pytest
from ai_station_runner import tailnet_api as api
from fastapi.testclient import TestClient
from test_tailnet_actions import finished, online
from test_tailnet_actions import runtime as runtime
from test_tailnet_service import manager as manager


@pytest.fixture
def client(runtime, monkeypatch):
    from ai_station_runner.app import app

    monkeypatch.setattr(api, "manager", lambda: runtime)
    monkeypatch.setattr(api, "paths", lambda: (runtime.root, runtime.binary_dir, "amd64"))
    monkeypatch.setattr(api, "verified_install", lambda *a: {})
    return TestClient(app), runtime


def body(operation, rid=None):
    return {"operation": operation, "run_id": rid or str(uuid4()), "permissions": ["manage_private_access"]}


def test_native_status_never_discloses_private_output(client):
    http, _ = client
    result = http.get("/v1/private-access")
    assert result.status_code == 200 and result.json()["installed"]
    assert "SECRET" not in result.text and "AuthURL" not in result.text


def test_native_rejects_permissions_extra_commands_and_origin_override(client):
    http, _ = client
    for permissions in ([], ["manage_station"], ["manage_private_access", "network_external"]):
        assert (
            http.post(
                "/v1/private-access/actions", json={**body("login"), "permissions": permissions}
            ).status_code
            == 403
        )
    assert http.post("/v1/private-access/actions", json={**body("login"), "argv": ["sh"]}).status_code == 422
    assert (
        http.post(
            "/v1/private-access/actions",
            json={**body("serve_on"), "node_id": "other", "origin": "https://evil.example"},
        ).status_code
        == 422
    )


def test_login_link_separate_and_cancellation_scope_frozen(client):
    http, service = client
    request = body("login")
    started = http.post("/v1/private-access/actions", json=request)
    assert started.status_code == 200 and "SECRET" not in started.text
    finished(service, request["run_id"])
    link = http.post("/v1/private-access/link", json=request)
    assert link.status_code == 200 and link.json()["url"].endswith("SECRET-LOGIN")
    assert http.post("/v1/private-access/link", json={**request, "operation": "serve_on"}).status_code == 409
    stopped = http.post("/v1/private-access/cancel", json=request)
    assert stopped.status_code == 200 and stopped.json()["process_confirmed_gone"]
    assert http.post("/v1/private-access/link", json=request).json()["url"] is None
    assert service.status()["state"] == "NeedsLogin"


def test_native_cancel_before_dispatch_and_late_delivery(client):
    http, service = client
    request = body("login")
    assert http.post("/v1/private-access/cancel", json=request).status_code == 200
    result = http.post("/v1/private-access/actions", json=request)
    assert result.status_code == 200 and result.json()["phase"] == "canceled"
    assert not (service.root / "operations" / (request["run_id"] + ".json")).exists()


def test_enable_and_disable_drain_owned_service_preserve_keys(client):
    http, service = client
    online(service)
    request = body("serve_on")
    assert (
        http.post(
            "/v1/private-access/actions",
            json={**request, "node_id": "node123", "origin": "https://ai-station.tail123.ts.net"},
        ).status_code
        == 200
    )
    assert finished(service, request["run_id"])["phase"] == "succeeded"
    assert (service.root / "desired.json").exists()
    response = http.post("/v1/private-access/actions", json=body("stop"))
    assert response.status_code == 200 and response.json()["phase"] == "succeeded"
    assert service.status()["state"] == "stopped"
    assert not (service.root / "desired.json").exists()
    assert (service.root / "tailscaled.state").read_text() == "SECRET-NODE-KEY"


@pytest.mark.parametrize("unsafe", ["keys", "binaries"])
def test_native_secrets_and_executables_cannot_enter_agent_roots(tmp_path, monkeypatch, unsafe):
    from types import SimpleNamespace

    allowed = tmp_path / "workspace"
    private = allowed / "keys" if unsafe == "keys" else tmp_path / "keys"
    binary = allowed / "runtime" if unsafe == "binaries" else tmp_path / "runtime"
    settings = SimpleNamespace(roots=lambda: [allowed], host_data_dir=lambda: tmp_path / "data", port=8765)
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(api, "paths", lambda: (private, binary, "amd64"))
    with pytest.raises(ValueError, match="outside every allowed"):
        api.manager()
    assert not private.exists() and not binary.exists()
