from uuid import uuid4

import pytest
from ai_station_runner import station_updates as module
from ai_station_runner.app import app
from fastapi.testclient import TestClient


def test_uninstalled_or_unqualified_native_updater_never_reports_operational(monkeypatch):
    monkeypatch.setenv("AI_STATION_DESKTOP_CONTROL_SOCKET", "")
    from ai_station_runner.config import clear_settings_cache

    clear_settings_cache()
    client = TestClient(app)
    assert client.get("/v1/station/updates/capabilities").json() == {
        "installed": False,
        "apply_available": False,
    }
    response = client.post(
        "/v1/station/updates",
        json={"action": "inspect", "run_id": str(uuid4()), "permissions": ["manage_station", "network_read"]},
    )
    assert response.status_code == 503


@pytest.mark.parametrize("platform", ["linux-amd64", "windows-x64"])
def test_native_operations_require_finite_input_and_station_management(monkeypatch, platform):
    seen = []

    def native(value):
        if value["action"] == "updates.capabilities":
            return {"installed": True, "platform": platform, "version": "0.5.0"}
        seen.append(value)
        return {"run_id": value["run_id"], "phase": "ready"}

    monkeypatch.setattr(module, "native", native)
    client = TestClient(app)
    body = {"action": "inspect", "run_id": str(uuid4()), "permissions": ["manage_station", "network_read"]}
    assert client.post("/v1/station/updates", json={**body, "permissions": []}).status_code == 403
    assert client.post("/v1/station/updates", json={**body, "command": "install"}).status_code == 422
    assert client.post("/v1/station/updates", json={**body, "action": "shell"}).status_code == 422
    assert client.post("/v1/station/updates", json={**body, "action": "resume"}).status_code == 422
    assert client.post("/v1/station/updates", json={**body, "native_resume": True}).status_code == 422
    assert (
        client.post(
            "/v1/station/updates", json={**body, "request": {"url": "https://other.example"}}
        ).status_code
        == 422
    )
    assert not seen
    assert client.post("/v1/station/updates", json=body).status_code == 200
    assert seen == [{"action": "updates.inspect", "run_id": body["run_id"]}]


def test_unqualified_platform_cannot_acquire_install_authority(monkeypatch):
    from ai_station_runner.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_DESKTOP_CONTROL_SOCKET", "/native/desktop-control.sock")
    clear_settings_cache()
    seen = []

    def native(value):
        seen.append(value)
        return {"installed": True, "platform": "macos-arm64", "version": "0.5.0"}

    monkeypatch.setattr(module, "native", native)
    client = TestClient(app)
    assert client.get("/v1/station/updates/capabilities").json()["apply_available"] is False
    reply = client.post(
        "/v1/station/updates",
        json={"action": "apply", "run_id": str(uuid4()), "permissions": ["manage_station", "network_read"]},
    )
    assert reply.status_code == 503
    assert seen == [{"action": "updates.capabilities"}] * 2


@pytest.mark.parametrize("requested", ["linux-amd64", "windows-x64"])
def test_prepare_uses_only_its_qualified_native_platform(monkeypatch, requested):
    seen = []

    def native(value):
        seen.append(value)
        return {"installed": True, "platform": "windows-x64", "version": "0.5.0"}

    monkeypatch.setattr(module, "native", native)
    client = TestClient(app)
    response = client.post(
        "/v1/station/updates",
        json={
            "action": "prepare",
            "run_id": str(uuid4()),
            "permissions": ["manage_station", "network_read"],
            "request": {
                "release_id": 10,
                "fingerprint": "a" * 64,
                "platform": requested,
                "current_version": "0.5.0",
            },
        },
    )
    assert response.status_code == (200 if requested == "windows-x64" else 422)
    assert [value["action"] for value in seen] == (
        ["updates.capabilities", "updates.prepare"]
        if requested == "windows-x64"
        else ["updates.capabilities"]
    )
