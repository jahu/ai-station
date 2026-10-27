"""Observed non-owned GPU occupancy defers the same durable load without native effects."""

from datetime import timedelta

import pytest
from app.api import app
from app.db import reset_engine, session_factory, utcnow
from app.llama import instances
from app.models import Run, Task
from app.resources import RESOURCE_WAIT_KEY, active_locks
from app.runner_client import RunnerClient
from app.runs import request_cancel
from fastapi.testclient import TestClient
from test_llama import load, tick_once
from test_llama import managed as managed  # noqa: F401


@pytest.mark.parametrize("field", ["used", "free"])
@pytest.mark.parametrize("occupied", [2, 7])
def test_observed_occupancy_waits_then_starts_original_load_after_clearance(
    managed, monkeypatch, field, occupied
):
    model_id, records = managed
    pressured = True

    def hardware(_):
        rows = []
        for index in [2, 7]:
            used = 8000 if pressured and index == occupied else 100
            rows.append(
                {
                    "index": index,
                    "memory_total_mib": 12288,
                    **({"memory_used_mib": used} if field == "used" else {"memory_free_mib": 12288 - used}),
                }
            )
        return {"gpus": rows, "memory": {"available_mib": 24000}}

    monkeypatch.setattr(RunnerClient, "hardware", hardware)
    with TestClient(app) as client:
        original = load(client, model_id)
        assert tick_once() == original["id"]
        waiting = client.get("/api/runs/" + original["id"]).json()
        assert waiting["status"] == "queued"
        assert waiting["resource_wait"]["reason"] == "gpu"
        assert waiting["resource_wait"]["available_mib"] == 24000
        assert waiting["resource_wait"]["required_mib"] == 0
        assert waiting["resource_wait"]["reserved_mib"] == 0
        assert waiting["resource_wait"]["headroom_mib"] == 1024
        assert waiting["resource_wait"]["gpu_memory"][0]["index"] == occupied
        assert not waiting["metadata"].get("dispatch_attempted")
        assert waiting["parameters"]["context_size"] == original["parameters"]["context_size"]
        assert records == {}
        with session_factory()() as session:
            assert not active_locks(session)
            assert instances(session)[0].metadata_json.get("context_fit") != "too_large"
            assert "failed_context_size" not in instances(session)[0].metadata_json
            task = session.get(Task, original["task_id"])
            assert task.metadata_json[RESOURCE_WAIT_KEY] > utcnow().isoformat()
        reset_engine()  # Persistence/requeue must not depend on an in-memory polling loop.
        assert tick_once() is None
        independent = client.post("/api/testing/runs", json={"title": "Independent CPU work"}).json()
        assert tick_once() == independent["id"]
        assert client.get("/api/runs/" + independent["id"]).json()["status"] == "succeeded"
        assert records == {}
        pressured = False
        with session_factory()() as session:
            task = session.get(Task, original["task_id"])
            task.metadata_json = {
                **task.metadata_json,
                RESOURCE_WAIT_KEY: (utcnow() - timedelta(seconds=1)).isoformat(),
            }
            session.commit()
        assert tick_once() == original["id"]
        final = client.get("/api/runs/" + original["id"]).json()
        assert final["status"] == "succeeded" and final["resource_wait"] is None
        assert list(records) == [original["parameters"]["instance_id"]]
        assert final["parameters"]["context_size"] == original["parameters"]["context_size"]
        with session_factory()() as session:
            assert instances(session)[0].metadata_json.get("context_fit") != "too_large"


def test_cancel_waiting_load_never_starts_gpu_process(managed, monkeypatch):
    model_id, records = managed
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {
            "gpus": [{"index": i, "memory_total_mib": 12288, "memory_used_mib": 8000} for i in [2, 7]]
        },
    )
    with TestClient(app) as client:
        original = load(client, model_id)
        tick_once()
        with session_factory()() as session:
            request_cancel(session, session.get(Run, original["id"]))
            session.commit()
        assert client.get("/api/runs/" + original["id"]).json()["status"] == "canceled"
        assert tick_once() is None and records == {}


def test_cpu_load_ignores_unrelated_gpu_occupancy(managed, monkeypatch):
    model_id, records = managed
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {"gpus": [{"index": 2, "memory_total_mib": 12288, "memory_used_mib": 11000}]},
    )
    with TestClient(app) as client:
        original = client.post("/api/llama/load", json={"model_file_id": model_id, "gpus": []}).json()
        assert tick_once() == original["id"]
        assert client.get("/api/runs/" + original["id"]).json()["status"] == "succeeded"
        assert len(records) == 1


def test_cancel_during_memory_admission_is_not_requeued_or_dispatched(managed, monkeypatch):
    model_id, records = managed

    def cancel_during_check(session, run, hardware):
        request_cancel(session, run)
        return False

    monkeypatch.setattr("app.llama_admission.memory_available", cancel_during_check)
    with TestClient(app) as client:
        original = load(client, model_id)
        assert tick_once() == original["id"]
        assert client.get("/api/runs/" + original["id"]).json()["status"] == "canceled"
        assert not records
        with session_factory()() as session:
            assert not active_locks(session)


def test_recovery_reattaches_same_dispatched_operation_despite_its_own_vram(managed, monkeypatch):
    model_id, records = managed
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {
            "gpus": [{"index": i, "memory_total_mib": 12288, "memory_used_mib": 11000} for i in [2, 7]]
        },
    )
    with TestClient(app) as client:
        original = load(client, model_id)
        iid = original["parameters"]["instance_id"]
        records[iid] = {"status": "ready", "alive": True, "gpus": [2, 7]}
        with session_factory()() as session:
            run = session.get(Run, original["id"])
            run.metadata_json = {"dispatch_attempted": True}
            session.commit()
        assert tick_once() == original["id"]
        assert client.get("/api/runs/" + original["id"]).json()["status"] == "succeeded"
        assert list(records) == [iid]
