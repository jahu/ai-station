"""Queued runtime preparation only; the unpublished native install flag fails closed."""

from uuid import uuid4

import pytest
from app.api import app
from app.db import control_session_factory
from app.model_setup import fingerprint
from app.models import Run, Task
from app.runner_client import RunnerClient
from app.runs import transition
from app.state import RunStatus
from fastapi.testclient import TestClient


@pytest.fixture
def runtime_catalog(monkeypatch, request):
    recipe = {
        "profile": getattr(request, "param", "llamacpp-cuda-linux-amd64-v1"),
        "name": "Synthetic local runtime",
        "image_reference": "ghcr.io/ggml-org/llama.cpp@sha256:" + "a" * 64,
        "download_bytes": 1024,
        "license": "Synthetic test license",
    }
    report = {
        "recipe": recipe,
        "manifest_sha256": fingerprint(recipe),
        "installation_available": True,
        "image": {"present": False, "status": "unavailable"},
    }
    monkeypatch.setattr(RunnerClient, "runtime_setup_catalog", lambda _, profile=None: report)
    return report


def body(catalog):
    return {
        "client_request_id": str(uuid4()),
        "profile": catalog["recipe"]["profile"],
        "manifest_sha256": catalog["manifest_sha256"],
        "license_accepted": True,
    }


def test_runtime_preparation_queues_only_and_reconciles_lost_ack(runtime_catalog):
    with TestClient(app) as api:
        payload = body(runtime_catalog)
        response = api.post("/api/setup/runtimes", json=payload)
        assert response.status_code == 202, response.text
        replay = api.post("/api/setup/runtimes", json=payload)
        assert replay.status_code == 202 and replay.json()["id"] == response.json()["id"]
        assert replay.json()["run"]["status"] == "queued"
        assert replay.json()["run"]["executor_type"] == "runtime_setup"
        assert replay.json()["run"]["execution_target"] == "host"
        with control_session_factory()() as db:
            task = db.get(Task, response.json()["id"])
            assert task.metadata_json["runtime_preparation"]["recipe"] == runtime_catalog["recipe"]
            assert db.get(Run, response.json()["run"]["id"]).parameters["recipe"] == runtime_catalog["recipe"]
        assert api.get("/api/setup/runtimes/preparations").json()[0]["id"] == response.json()["id"]


@pytest.mark.parametrize(
    "change",
    [
        {"license_accepted": False},
        {"license_accepted": 1},
        {"manifest_sha256": "f" * 64},
        {"image_reference": "unreviewed/image:tag"},
        {"command": ["id"]},
    ],
)
def test_unreviewed_source_or_license_never_queues(runtime_catalog, change):
    with TestClient(app) as api:
        response = api.post("/api/setup/runtimes", json={**body(runtime_catalog), **change})
        assert response.status_code in (409, 422), response.text
        assert api.get("/api/setup/runtimes/preparations").json() == []


def test_unqualified_adapter_cannot_be_enabled_by_a_caller(runtime_catalog):
    runtime_catalog["installation_available"] = False
    with TestClient(app) as api:
        response = api.post("/api/setup/runtimes", json=body(runtime_catalog))
        assert response.status_code == 409, response.text
        assert api.get("/api/setup/runtimes/preparations").json() == []


def test_stop_before_claim_and_resume_keep_frozen_recipe_and_submission_receipts(runtime_catalog):
    with TestClient(app) as api:
        response = api.post("/api/setup/runtimes", json=body(runtime_catalog))
        assert response.status_code == 202, response.text
        path = "/api/setup/runtimes/preparations/" + response.json()["id"]
        stopped = api.post(path + "/cancel")
        assert stopped.status_code == 200 and stopped.json()["run"]["status"] == "canceled"
        original = runtime_catalog["recipe"].copy()
        runtime_catalog["recipe"] = {**original, "image_reference": "different/image:tag"}
        request = {"client_request_id": str(uuid4()), "expected_run_id": response.json()["run"]["id"]}
        resumed = api.post(path + "/resume", json=request)
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["recipe"] == original and resumed.json()["attempt"] == 2
        assert api.post(path + "/resume", json=request).json()["run"]["id"] == resumed.json()["run"]["id"]
        assert (
            api.post(path + "/resume", json={**request, "expected_run_id": str(uuid4())}).status_code == 409
        )


def test_uncertain_native_cleanup_disables_resume(runtime_catalog):
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()
        with control_session_factory()() as db:
            run = db.get(Run, created["run"]["id"])
            transition(db, run, RunStatus.CLAIMED, event_type="run.claimed")
            transition(db, run, RunStatus.INTERRUPTED, event_type="run.interrupted")
            run.metadata_json = {"cleanup_requires_inspection": True}
            db.commit()
        path = "/api/setup/runtimes/preparations/" + created["id"]
        assert api.get(path).json()["resume_allowed"] is False
        assert (
            api.post(
                path + "/resume",
                json={"client_request_id": str(uuid4()), "expected_run_id": created["run"]["id"]},
            ).status_code
            == 409
        )


@pytest.mark.parametrize("runtime_catalog", ["llamacpp-cpu-linux-amd64-v1"], indirect=True)
def test_cpu_profile_keeps_the_owned_preparation_queue_and_resume_identity(runtime_catalog):
    with TestClient(app) as api:
        payload = body(runtime_catalog)
        report = api.get("/api/setup/runtimes", params={"profile": payload["profile"]})
        assert report.status_code == 200 and report.json()["recipe"]["profile"] == payload["profile"]
        created = api.post("/api/setup/runtimes", json=payload)
        assert created.status_code == 202
        value = created.json()
        assert value["run"]["executor_type"] == "runtime_setup"
        assert value["run"]["parameters"]["recipe"] == runtime_catalog["recipe"]
        path = "/api/setup/runtimes/preparations/" + value["id"]
        assert api.post(path + "/cancel", json={}).json()["run"]["status"] == "canceled"
        resumed = api.post(
            path + "/resume", json={"client_request_id": str(uuid4()), "expected_run_id": value["run"]["id"]}
        )
        assert resumed.status_code == 202 and resumed.json()["attempt"] == 2
        assert resumed.json()["recipe"] == value["recipe"]
        assert api.get("/api/setup/runtimes/preparations").json() == []
        assert (
            len(api.get("/api/setup/runtimes/preparations", params={"profile": payload["profile"]}).json())
            == 1
        )
