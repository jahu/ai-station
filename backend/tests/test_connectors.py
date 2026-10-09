import json

import httpx
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Connector, Notice
from fastapi.testclient import TestClient
from sqlalchemy import select


def drain(session, worker="connector-test", limit=20):
    for _ in range(limit):
        if tick(session, worker) is None:
            return
    raise AssertionError("worker queue did not drain")


def _client(handle, monkeypatch, address="93.184.216.34"):
    from app import http_fetch

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handle))
    )
    monkeypatch.setattr(
        http_fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", (address, 0))],
    )


def test_kinds_keep_unavailable_adapters_unpublished():
    api = TestClient(app)
    kinds = {item["kind"]: item for item in api.get("/api/connectors/kinds").json()}
    assert kinds["http"]["operational"] is True
    for kind in ("browser", "github", "email", "calendar", "social"):
        assert kinds[kind]["operational"] is False
    rejected = api.post(
        "/api/connectors",
        json={"key": "gh", "name": "GitHub", "kind": "github", "url": "https://api.github.com/user"},
    )
    assert rejected.status_code == 422


def test_http_connector_stores_secret_reference_and_checks_public_get(monkeypatch):
    monkeypatch.setenv("AI_STATION_HTTP_TOKEN", "sk-connector-secret")
    seen = {}

    def handle(request):
        seen["authorization"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok public")

    _client(handle, monkeypatch)
    api = TestClient(app)
    created = api.post(
        "/api/connectors",
        json={
            "key": "status-page",
            "name": "Status page",
            "url": "https://www.example.com/status",
            "secret_ref": "env:AI_STATION_HTTP_TOKEN",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    dumped = json.dumps(body)
    assert "sk-connector-secret" not in dumped
    assert body["secret_ref"] == "env:AI_STATION_HTTP_TOKEN"
    assert body["secret_source"] == "env"
    assert body["method"] == "GET"
    assert body["health"] == "unknown"
    private = api.post(
        "/api/connectors",
        json={"key": "loopback", "name": "Local", "url": "http://127.0.0.1/secret"},
    )
    assert private.status_code == 422
    queued = api.post(f"/api/connectors/{body['id']}/check")
    assert queued.status_code == 202, queued.text
    assert queued.json()["effective_permissions"] == ["network_read"]
    with session_factory()() as session:
        drain(session)
        row = session.get(Connector, body["id"])
        assert row.health == "healthy" and row.status == "ready"
    detail = api.get(f"/api/connectors/{body['id']}").json()
    assert detail["health"] == "healthy"
    run = api.get("/api/runs/" + detail["last_run_id"]).json()
    assert run["status"] == "succeeded"
    assert "sk-connector-secret" not in json.dumps(run)
    artifacts = api.get("/api/artifacts?run_id=" + run["id"]).json()
    assert artifacts and artifacts[0]["type"] == "json"
    assert seen["authorization"] == "Bearer sk-connector-secret"
    assert seen["url"] == "https://www.example.com/status"


def test_missing_secret_fails_closed_and_unavailable_kinds_stay_disabled(monkeypatch):
    monkeypatch.delenv("AI_STATION_HTTP_TOKEN", raising=False)
    api = TestClient(app)
    created = api.post(
        "/api/connectors",
        json={
            "key": "needs-secret",
            "name": "Needs secret",
            "url": "https://www.example.com/",
            "secret_ref": "env:AI_STATION_HTTP_TOKEN",
        },
    )
    assert created.status_code == 201
    assert created.json()["secret_present"] is False
    blocked = api.post(f"/api/connectors/{created.json()['id']}/check")
    assert blocked.status_code == 409
    assert "secret" in blocked.json()["detail"].lower()
    with session_factory()() as session:
        assert list(session.scalars(select(Notice))) == []


def test_queued_http_check_can_be_canceled_without_calling_the_url():
    api = TestClient(app)
    created = api.post(
        "/api/connectors",
        json={"key": "docs", "name": "Docs", "url": "https://www.example.com/docs"},
    )
    queued = api.post(f"/api/connectors/{created.json()['id']}/check")
    assert queued.status_code == 202
    canceled = api.post(f"/api/runs/{queued.json()['id']}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    detail = api.get(f"/api/connectors/{created.json()['id']}").json()
    assert detail["status"] == "unconfigured"
    assert detail["health"] == "unknown"
