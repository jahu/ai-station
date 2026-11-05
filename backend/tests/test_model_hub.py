"""Durable private model-source inspection, with no real network/model execution."""

from uuid import uuid4

import pytest
from app import model_hub
from app.api import app
from app.db import control_session_factory
from app.engine import tick
from app.models import Artifact, ModelDefinition, ModelFile, Run, User
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_account_private_api import accounts, private_app  # noqa: F401


def body(**updates):
    return {"source": "publisher/model", "client_request_id": str(uuid4()), **updates}


def work():
    with control_session_factory()() as session:
        return tick(session, "hub-test")


@pytest.fixture
def source(monkeypatch):
    calls = []

    async def inspect(source, check):
        check()
        calls.append(source)
        return {"repository": source.repository, "revision": "a" * 40, "files": [], "metadata_only": True}

    monkeypatch.setattr(model_hub, "inspect_source", inspect)
    monkeypatch.setattr(model_hub.RunnerClient, "hardware", lambda self: {"memory": {}, "gpus": []})
    monkeypatch.setattr(model_hub, "storage_info", lambda hardware: None)
    return calls


def test_http_only_enqueues_idempotently_and_worker_publishes_report(source):
    with TestClient(app) as api:
        request = body()
        response = api.post("/api/model-hub/inspections", json=request)
        assert response.status_code == 202, response.text
        identity = response.json()["id"]
        assert not source
        assert api.post("/api/model-hub/inspections", json=request).json()["id"] == identity
        assert (
            api.post("/api/model-hub/inspections", json={**request, "source": "different/model"}).status_code
            == 409
        )
        work()
        saved = api.get(f"/api/runs/{identity}").json()
        assert saved["status"] == "succeeded", saved
        report = saved["metadata"]["source_inspection"]
        assert report["no_weights_downloaded"] and len(source) == 1
        artifact = saved["metadata"]["inspection_artifact_id"]
        assert api.get(f"/api/artifacts/{artifact}/file").json() == report
    with control_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(ModelFile)) == 0
        assert session.scalar(select(func.count()).select_from(ModelDefinition)) == 0


@pytest.mark.parametrize(
    "extra", [{"command": "curl evil"}, {"sha256": "a" * 64}, {"destination": "/tmp/model"}]
)
def test_api_never_accepts_download_execution_or_hash_overrides(extra, source):
    with TestClient(app) as api:
        assert api.post("/api/model-hub/inspections", json={**body(), **extra}).status_code == 422
        assert not source


def test_stop_before_worker_never_contacts_source(source):
    with TestClient(app) as api:
        identity = api.post("/api/model-hub/inspections", json=body()).json()["id"]
        assert api.post(f"/api/runs/{identity}/cancel").status_code == 200
        work()
        assert api.get(f"/api/runs/{identity}").json()["status"] == "canceled"
        assert not source


@pytest.mark.parametrize("action", ["cancel", "replace", "task_stop"])
def test_stop_or_claim_replacement_during_network_never_publishes(monkeypatch, source, action):
    async def inspect(source, check):
        with control_session_factory()() as db:
            run = db.scalar(select(Run).where(Run.executor_type == "model_hub_inspect"))
            if action == "cancel":
                request_cancel(db, run)
            elif action == "task_stop":
                run.task.metadata_json = {**run.task.metadata_json, "stop_requested_at": "fixture-stop"}
            else:
                run.worker_id = "replacement"
            db.commit()
        check()
        if action == "task_stop":
            return {"repository": "publisher/model", "revision": "a" * 40, "files": []}
        raise AssertionError("Lost claim/Stop must end the inspection")

    monkeypatch.setattr(model_hub, "inspect_source", inspect)
    with TestClient(app) as api:
        identity = api.post("/api/model-hub/inspections", json=body()).json()["id"]
        work()
        saved = api.get(f"/api/runs/{identity}").json()
        assert saved["status"] == ("running" if action == "replace" else "canceled")
        assert "source_inspection" not in saved["metadata"]
    with control_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Artifact)) == 0


def test_real_private_policy_requires_admin_and_keeps_report_private(accounts, source):  # noqa: F811
    owner, alice, bob = accounts
    assert alice.post("/api/model-hub/inspections", json=body()).status_code == 403
    identity = owner.post("/api/model-hub/inspections", json=body()).json()["id"]
    work()
    report = owner.get(f"/api/runs/{identity}").json()
    assert report["status"] == "succeeded", report
    assert alice.get(f"/api/runs/{identity}").status_code == 404
    artifact = report["metadata"]["inspection_artifact_id"]
    assert bob.get(f"/api/artifacts/{artifact}/file").status_code == 404


def test_revoked_admin_cannot_run_queued_inspection(accounts, source):  # noqa: F811
    owner, _, _ = accounts
    identity = owner.post("/api/model-hub/inspections", json=body()).json()["id"]
    owner_id = owner.get("/api/auth").json()["user"]["id"]
    with control_session_factory()() as db:
        db.get(User, owner_id).is_admin = False
        db.commit()
    work()
    assert not source
    with control_session_factory()() as db:
        assert db.get(Run, identity).status == "failed"


def test_search_enqueues_without_network_or_native_hardware_and_retains_its_result(source, monkeypatch):
    calls = []

    async def search(query, check):
        check()
        calls.append(query)
        return {"kind": "search", "query": query, "items": [], "files": [], "metadata_only": True}

    monkeypatch.setattr(model_hub, "search_models", search)

    def forbidden(*args):
        raise AssertionError("Searching repository names needs no hardware call")

    monkeypatch.setattr(model_hub.RunnerClient, "hardware", forbidden)
    with TestClient(app) as api:
        request = {"query": "new model", "client_request_id": str(uuid4())}
        response = api.post("/api/model-hub/searches", json=request)
        assert response.status_code == 202 and not calls and not source
        assert api.post("/api/model-hub/searches", json=request).json()["id"] == response.json()["id"]
        assert (
            api.post(
                "/api/model-hub/inspections",
                json={"source": "p/model", "client_request_id": request["client_request_id"]},
            ).status_code
            == 409
        )
        work()
        saved = api.get("/api/runs/" + response.json()["id"]).json()
        assert saved["status"] == "succeeded", saved
        assert calls == ["new model"]
        assert saved["metadata"]["source_inspection"]["kind"] == "search"
