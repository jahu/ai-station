from app.api import app
from app.db import reset_engine, session_factory
from app.engine import tick
from fastapi.testclient import TestClient


def test_fake_executor_api_persists_and_replays():
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        response = client.post("/api/testing/runs", json={"title": "smoke"})
        assert response.status_code == 202
        run = response.json()
        assert run["status"] == "queued"
        with session_factory()() as session:
            tick(session, "test-worker")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"
        reset_engine()
        assert len(client.get("/api/runs").json()) == 1
        events = client.get(f"/api/runs/{run['id']}/events").json()
        response = client.get(f"/api/runs/{run['id']}/stream", headers={"Last-Event-ID": "3"})
        assert "id: 3\n" not in response.text
        assert "run.completed" in response.text
        assert "event: end" in response.text
        assert len(events) == 6


def test_api_validation_and_cancel():
    with TestClient(app) as client:
        assert client.get("/api/runs/not-a-uuid").status_code == 422
        assert client.get("/api/runs?status=unknown").status_code == 422
        assert client.get("/api/runs?limit=99999").status_code == 422
        assert client.post("/api/testing/runs", json={"command": "anything"}).status_code == 422
        response = client.post("/api/testing/runs", json={}, headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        run = client.post("/api/testing/runs", json={}).json()
        result = client.post(f"/api/runs/{run['id']}/cancel").json()
        assert result["status"] == "canceled"
        assert result["cancellation_requested_at"]
        assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 409
        assert client.get("/api/system/hardware").status_code == 503
