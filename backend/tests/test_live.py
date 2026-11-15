from types import SimpleNamespace
from uuid import uuid4

import pytest
from app import live
from app.db import control_session_factory
from app.live_executor import LiveExecutor
from app.models import Run
from app.resources import active_locks, reserve_gpu_bundle
from app.runner_client import RunnerClient
from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload


@pytest.fixture
def ready(monkeypatch):
    result = {
        "available": True,
        "eligible_gpu_indices": [3, 7],
        "ram_mib": 12288,
        "managed_runtime": {
            "profile": "live-identity-linux-x86-64-python312-v1",
            "manifest_sha256": "a" * 64,
            "environment_id": "b" * 64,
        },
    }
    monkeypatch.setattr(
        RunnerClient,
        "request",
        lambda self, method, path, json=None: (
            result
            if path == "/v1/live/capabilities"
            else pytest.fail("An enqueue handler dispatched native work")
        ),
    )
    return result


def submit(browser, source, client_request_id=None):
    return browser.post(
        "/api/live/sessions",
        json={"client_request_id": client_request_id or str(uuid4()), "image_artifact_id": source},
    )


def test_live_sessions_are_private_and_start_is_idempotent(accounts, ready):
    owner, alice, bob = accounts
    source, _ = upload(alice, "green")
    token = str(uuid4())
    first = submit(alice, source, token)
    assert first.status_code == 202, first.text
    run = first.json()["run"]
    assert run["status"] == "queued" and not first.json()["ready"]
    assert run["parameters"]["image_artifact_id"] == source
    assert submit(alice, source, token).json()["run"]["id"] == run["id"]
    assert len(alice.get("/api/live/sessions").json()) == 1
    assert bob.get("/api/live/sessions").json() == []
    assert owner.get("/api/live/sessions").json() == []
    assert bob.get("/api/live/sessions/" + run["id"]).status_code == 404
    assert submit(bob, source).status_code == 422
    assert submit(bob, source, token).status_code == 422
    bob_source, _ = upload(bob, "blue")
    assert submit(bob, bob_source, token).status_code == 409
    assert alice.post("/api/runs/" + run["id"] + "/cancel").status_code == 200
    assert alice.get("/api/live/sessions/" + run["id"]).json()["run"]["status"] == "canceled"


def test_live_refuses_unavailable_engine_and_unselected_media(accounts, ready):
    _, alice, _ = accounts
    source, _ = upload(alice, "green")
    ready["available"] = False
    ready["reason"] = "Prepare the reviewed Live runtime"
    assert submit(alice, source).status_code == 409
    assert alice.post("/api/live/sessions", json={"client_request_id": str(uuid4())}).status_code == 422
    assert alice.get("/api/live/sessions").json() == []


def websocket_for(browser, headers=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(account_access_enabled=True)),
        headers=headers or {"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"},
        cookies=dict(browser.cookies),
    )


def test_stream_rechecks_device_owner_reference_and_exact_origin(accounts, ready):
    _, alice, bob = accounts
    source, _ = upload(alice, "green")
    identity = submit(alice, source).json()["run"]["id"]
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        run.status = "running"
        run.metadata_json = {"live_ready": True}
        session.commit()
    websocket = websocket_for(alice)
    principal = live.authorize_stream(websocket, identity)
    assert principal.user_id
    with pytest.raises(HTTPException):
        live.authorize_stream(websocket_for(bob), identity)
    for origin in ("http://localhost:9999", "http://127.0.0.1:9999", "https://evil.example"):
        with pytest.raises(PermissionError):
            live.authorize_stream(
                websocket_for(alice, {"host": "127.0.0.1:8765", "origin": origin}), identity
            )
    with control_session_factory()() as session:
        from app.models import Artifact

        session.get(Artifact, source).trashed_at = live.utcnow()
        session.commit()
    with pytest.raises(ValueError):
        live.authorize_stream(websocket, identity, principal)
    alice.post("/api/auth/logout")
    with pytest.raises(PermissionError):
        live.authorize_stream(websocket, identity, principal)


def test_live_duplex_reservation_and_disconnect_release_are_atomic(accounts, ready):
    _, alice, _ = accounts
    source, _ = upload(alice, "green")
    identity = submit(alice, source).json()["run"]["id"]
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        run.status = "running"
        assert reserve_gpu_bundle(session, run, [3, 7], 2) == "3"
        assert len(active_locks(session)) == 2
        LiveExecutor().on_inspection(
            session, run, {"alive": False, "exit_code": 75, "stdout": '{"live_ready":true}\n'}
        )
        assert run.status == "interrupted"
        assert run.metadata_json["process_confirmed_gone"] and not run.metadata_json["live_ready"]
        assert not active_locks(session)


def test_wrong_origin_is_refused_before_native_stream_open(accounts, ready):
    _, alice, _ = accounts
    source, _ = upload(alice, "green")
    identity = submit(alice, source).json()["run"]["id"]
    with pytest.raises(WebSocketDisconnect):
        with alice.websocket_connect(
            f"/api/live/sessions/{identity}/stream", headers={"origin": "https://evil.example"}
        ):
            pytest.fail("Cross-origin live stream was accepted")


@pytest.mark.parametrize("reachable", [True, False])
def test_revoked_live_account_can_only_stop_its_existing_native_process(
    accounts, ready, monkeypatch, reachable
):
    from app.live_executor import LiveRunnerClient
    from app.models import User
    from app.revoked_runtime_setup import cleanup_revoked_runtime_setup
    from app.runner_client import RunnerUnavailable

    _, alice, _ = accounts
    source, _ = upload(alice, "green")
    identity = submit(alice, source).json()["run"]["id"]
    calls = []

    def cancel(client, run_id):
        calls.append(run_id)
        if not reachable:
            raise RunnerUnavailable("offline")
        return {"run_id": run_id, "executor": "live_identity", "alive": False, "status": "canceled"}

    monkeypatch.setattr(LiveRunnerClient, "cancel_process", cancel)
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        run.status, run.worker_id = "running", "cleanup-worker"
        run.metadata_json = {"dispatch_attempted": True}
        reserve_gpu_bundle(session, run, [3], 1)
        session.get(User, run.owner_id).enabled = False
        session.commit()
        assert cleanup_revoked_runtime_setup(session, run, "cleanup-worker")
        assert calls == [identity]
        assert run.status == ("canceled" if reachable else "cancel_requested")
        assert bool(active_locks(session)) is not reachable
