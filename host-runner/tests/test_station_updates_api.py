from uuid import uuid4

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


def test_native_operations_require_finite_input_and_station_management(monkeypatch):
    seen = []
    monkeypatch.setattr(module, "APPLY_QUALIFIED", True)
    monkeypatch.setattr(
        module, "native", lambda value: seen.append(value) or {"run_id": value["run_id"], "phase": "ready"}
    )
    client = TestClient(app)
    body = {"action": "inspect", "run_id": str(uuid4()), "permissions": ["manage_station", "network_read"]}
    assert client.post("/v1/station/updates", json={**body, "permissions": []}).status_code == 403
    assert client.post("/v1/station/updates", json={**body, "command": "install"}).status_code == 422
    assert client.post("/v1/station/updates", json={**body, "action": "shell"}).status_code == 422
    assert (
        client.post(
            "/v1/station/updates", json={**body, "request": {"url": "https://other.example"}}
        ).status_code
        == 422
    )
    assert not seen
    assert client.post("/v1/station/updates", json=body).status_code == 200
    assert seen == [{"action": "updates.inspect", "run_id": body["run_id"]}]
