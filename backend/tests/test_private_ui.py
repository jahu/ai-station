"""Operator authority, durable queue, recovery and exact managed-origin policy."""

from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run, RunEvent, Setting
from app.private_ui import PrivateAccessExecutor
from app.private_ui_state import KEY
from app.recovery import recover_stale
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import claim_next, request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select

PASSWORD = "private-operator-password"
ORIGIN = "https://ai-station.tail123.ts.net"


@pytest.fixture
def operator(monkeypatch):
    calls = []
    service = {
        "state": "Running",
        "installed": True,
        "available": True,
        "node_online": True,
        "node_id": "node123",
        "origin": ORIGIN,
        "serving": False,
    }

    def request(_client, method, path, json=None):
        calls.append((method, path, json))
        if path.endswith("/link"):
            return {"url": "https://login.tailscale.com/a/PRIVATE-LOGIN"}
        if method == "GET":
            return dict(service)
        if json["operation"] == "serve_on":
            service["serving"] = True
        if json["operation"] == "stop":
            service.update(state="stopped", serving=False)
        return {"phase": "succeeded", "process_confirmed_gone": True, "service": dict(service)}

    monkeypatch.setattr(RunnerClient, "request", request)
    client = TestClient(app)
    assert client.put("/api/operator-auth", json={"password": PASSWORD}).status_code == 200
    return client, calls, service


def queue(client, operation="start", revision=0, **extra):
    return client.post(
        "/api/private-access",
        json={
            "operation": operation,
            "expected_revision": revision,
            "client_request_id": str(uuid4()),
            **extra,
        },
    )


def work():
    with session_factory()() as session:
        return tick(session, "private-worker", executors={"private_access": PrivateAccessExecutor()})


def test_password_required_and_http_handlers_only_enqueue(operator):
    client, calls, _ = operator
    guest = TestClient(app)
    assert queue(guest).status_code == 401
    response = queue(client)
    assert response.status_code == 202
    assert calls == []
    run = response.json()
    assert run["status"] == "queued" and run["effective_permissions"] == ["manage_private_access"]
    assert client.post("/api/operator-auth/clear", json={"current_password": PASSWORD}).status_code == 409
    assert work() == run["id"]
    assert [call[1] for call in calls] == ["/v1/private-access/actions"]
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"


def test_receipt_replay_busy_revision_and_scope(operator):
    client, calls, _ = operator
    body = {"operation": "login", "expected_revision": 0, "client_request_id": str(uuid4())}
    first = client.post("/api/private-access", json=body)
    assert first.status_code == 202
    assert client.post("/api/private-access", json=body).json()["id"] == first.json()["id"]
    assert client.post("/api/private-access", json={**body, "operation": "start"}).status_code == 409
    assert queue(client).status_code == 409
    work()
    assert queue(client, revision=0).status_code == 409
    assert calls[0][2]["operation"] == "login"


@pytest.mark.parametrize(
    "extra",
    [
        {"origin": "https://evil.example", "node_id": "node123"},
        {"origin": ORIGIN + ":443", "node_id": "node123"},
        {"origin": ORIGIN + "/", "node_id": "node123"},
        {"origin": ORIGIN, "node_id": None},
    ],
)
def test_enable_needs_exact_reviewed_device(operator, extra):
    assert queue(operator[0], "enable", **extra).status_code == 422
    assert operator[1] == []


def test_enable_origin_password_rotation_secure_cookie_and_disable(operator):
    client, calls, _ = operator
    result = queue(client, "enable", node_id="node123", origin=ORIGIN)
    assert result.status_code == 202
    assert TestClient(app, base_url=ORIGIN).get("/api/health").status_code == 400
    work()
    phone = TestClient(app, base_url=ORIGIN)
    assert phone.get("/api/runs").status_code == 401
    login = phone.post("/api/operator-auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN})
    assert login.status_code == 200 and "; Secure" in login.headers["set-cookie"]
    assert phone.get("/api/runs").status_code == 200
    assert (
        phone.post("/api/private-access", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert (
        client.put(
            "/api/operator-auth", json={"password": PASSWORD + "new", "current_password": PASSWORD}
        ).status_code
        == 200
    )
    assert phone.get("/api/runs").status_code == 401
    assert phone.post("/api/operator-auth/login", json={"password": PASSWORD + "new"}).status_code == 200
    assert queue(client, "disable", revision=1).status_code == 202
    assert phone.get("/api/health").status_code == 400  # Revocation is immediate.
    work()
    status = client.get("/api/private-access").json()
    assert not status["enabled"] and status["approved_origin"] is None
    assert (
        client.post("/api/operator-auth/clear", json={"current_password": PASSWORD + "new"}).status_code
        == 200
    )
    assert [c[2]["operation"] for c in calls if c[1].endswith("/actions")] == ["serve_on", "stop"]


def test_password_change_invalidates_queued_authority(operator):
    client, calls, _ = operator
    result = queue(client)
    assert (
        client.put(
            "/api/operator-auth", json={"password": PASSWORD + "new", "current_password": PASSWORD}
        ).status_code
        == 200
    )
    work()
    assert not calls
    assert client.get(f"/api/runs/{result.json()['id']}").json()["status"] == "failed"


def test_login_link_is_authenticated_no_store_and_not_in_events(operator):
    client, _, _ = operator
    rid = queue(client, "login").json()["id"]
    work()
    guest = TestClient(app)
    assert guest.get(f"/api/private-access/actions/{rid}/link").status_code == 401
    result = client.get(f"/api/private-access/actions/{rid}/link")
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json()["url"].endswith("/PRIVATE-LOGIN")
    with session_factory()() as session:
        assert "PRIVATE-LOGIN" not in str(session.get(Run, rid).parameters)
        assert "PRIVATE-LOGIN" not in str([e.payload for e in session.scalars(select(RunEvent))])


def test_queued_stop_never_dispatches(operator):
    client, calls, _ = operator
    rid = queue(client).json()["id"]
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 200
    work()
    assert not calls
    assert client.get(f"/api/runs/{rid}").json()["status"] == "canceled"


def test_stale_dispatched_run_inspects_without_replay(operator):
    client, calls, _ = operator
    rid = queue(client).json()["id"]
    with session_factory()() as session:
        run = claim_next(session, "vanished")
        run.metadata_json = {"dispatch_attempted": True}
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert rid in recover_stale(session)
        session.commit()
    work()
    assert [c[1] for c in calls] == ["/v1/private-access/inspect"]
    assert client.get(f"/api/runs/{rid}").json()["status"] == "succeeded"


def test_stale_cancellation_is_forwarded_to_private_transport(operator):
    client, calls, _ = operator
    rid = queue(client, "login").json()["id"]
    with session_factory()() as session:
        run = claim_next(session, "vanished")
        run.metadata_json = {"dispatch_attempted": True}
        request_cancel(session, run)
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert rid in recover_stale(session)
        session.commit()
    work()
    assert [c[1] for c in calls] == ["/v1/private-access/inspect", "/v1/private-access/cancel"]
    assert client.get(f"/api/runs/{rid}").json()["status"] == "canceled"


def test_missing_password_with_saved_origin_fails_closed(operator):
    client, _, _ = operator
    queue(client, "enable", node_id="node123", origin=ORIGIN)
    work()
    with session_factory()() as session:
        session.delete(session.get(Setting, "operator_auth"))
        session.commit()
    phone = TestClient(app, base_url=ORIGIN)
    assert phone.get("/api/runs").status_code == 401
    assert phone.put("/api/operator-auth", json={"password": PASSWORD}).status_code == 401


def test_changed_native_endpoint_never_publishes_an_origin(operator, monkeypatch):
    client, _, _ = operator
    queued = queue(client, "enable", node_id="node123", origin=ORIGIN).json()
    monkeypatch.setattr(
        RunnerClient,
        "request",
        lambda *a, **k: {
            "phase": "succeeded",
            "process_confirmed_gone": True,
            "service": {"serving": True, "node_id": "replaced", "origin": ORIGIN},
        },
    )
    work()
    with session_factory()() as session:
        assert session.get(Setting, KEY).value["enabled"] is False
        assert session.get(Run, queued["id"]).status == "interrupted"


def test_unreachable_native_dispatch_is_inspected_without_secret_error_leaks(operator, monkeypatch):
    client, _, _ = operator
    rid = queue(client, "login").json()["id"]

    def unavailable(*_a, **_k):
        raise RunnerUnavailable("https://login.tailscale.com/a/DO-NOT-LOG")

    monkeypatch.setattr(RunnerClient, "request", unavailable)
    work()
    with session_factory()() as session:
        run = session.get(Run, rid)
        assert run.status not in {"failed", "canceled", "succeeded"}
        assert run.metadata_json["dispatch_attempted"]
        assert "DO-NOT-LOG" not in str([e.payload for e in session.scalars(select(RunEvent))])
