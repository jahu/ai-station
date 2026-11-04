"""Worker/account/recovery contracts use fake native facts and temporary databases."""

import copy
import json
from datetime import timedelta

import pytest
from app.api import app
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import Artifact, ResourceLock, Run, RunEvent
from app.recovery import recover_stale
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import claim_next, request_cancel, transition
from app.runtime_setup_job import payload
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_runtime_setup_api import body
from test_runtime_setup_api import runtime_catalog as runtime_catalog


@pytest.fixture
def bridge(runtime_catalog, monkeypatch):
    state = {
        "requests": [],
        "starts": {},
        "cancels": [],
        "inspect": [],
        "callback": None,
        "offline": False,
        "requires_inspection": False,
    }
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"memory": {"available_mib": 16000}})

    def result(identity, status="succeeded"):
        saved = state["starts"].get(identity)
        return {
            "run_id": identity,
            "status": status,
            "alive": False,
            "requires_inspection": state["requires_inspection"],
            "manifest_sha256": saved["manifest_sha256"] if saved else None,
            "image": {
                "id": "sha256:" + "b" * 64,
                "reference": runtime_catalog["recipe"]["image_reference"],
                "platform": "linux/amd64",
            }
            if status == "succeeded"
            else None,
            "process": None,
        }

    def start(self, value):
        if state["offline"]:
            raise RunnerUnavailable("Synthetic offline Runner")
        state["requests"].append(copy.deepcopy(value))
        state["starts"].setdefault(value["run_id"], copy.deepcopy(value))
        return {**result(value["run_id"]), "status": "running", "alive": True}

    def inspect(self, identity, **offsets):
        state["inspect"].append((identity, offsets))
        if state["offline"]:
            raise RunnerUnavailable("Synthetic offline Runner")
        callback = state.pop("callback", None)
        if callback:
            callback(identity)
        state["callback"] = None
        log = (
            json.dumps({"type": "runtime.prepare.progress", "stage": "downloading", "received_bytes": 512})
            + "\n"
        )
        return {
            **result(identity),
            "alive": state.get("keep_running", False),
            "status": "running" if state.get("keep_running") else "succeeded",
            "process": {
                "pid": 77,
                "process_group_id": 77,
                "stdout": log,
                "stderr": "",
                "stdout_offset": len(log),
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
                "stdout_log": f"runs/{identity}/stdout.log",
                "stderr_log": f"runs/{identity}/stderr.log",
            },
        }

    def cancel(self, identity, value):
        if state["offline"]:
            raise RunnerUnavailable("Synthetic offline Runner")
        state["cancels"].append((identity, value))
        return result(identity, "canceled")

    monkeypatch.setattr(RunnerClient, "prepare_runtime", start)
    monkeypatch.setattr(RunnerClient, "inspect_runtime_preparation", inspect)
    monkeypatch.setattr(RunnerClient, "cancel_runtime_preparation", cancel)
    return state


def work():
    with control_session_factory()() as db:
        return tick(db, "runtime-setup-worker")


def test_worker_publishes_one_private_receipt_with_real_source_progress(runtime_catalog, bridge):
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog))
        assert created.status_code == 202, created.text
        identity = created.json()["run"]["id"]
        assert work() == identity
        value = api.get("/api/runs/" + identity).json()
        assert value["status"] == "succeeded", value
        with control_session_factory()() as db:
            outputs = list(db.scalars(select(Artifact).where(Artifact.run_id == identity)))
            assert len(outputs) == 1 and outputs[0].artifact_type == "json"
            assert db.scalar(
                select(RunEvent.id).where(
                    RunEvent.run_id == identity, RunEvent.event_type == "runtime.prepare.progress"
                )
            )
            assert all(
                row.released_at
                for row in db.scalars(select(ResourceLock).where(ResourceLock.run_id == identity))
            )
        assert len(bridge["starts"]) == 1
        assert bridge["requests"][0]["manifest_sha256"] == created.json()["manifest_sha256"]


def dispatched(api, runtime_catalog, bridge):
    created = api.post("/api/setup/runtimes", json=body(runtime_catalog))
    assert created.status_code == 202, created.text
    with control_session_factory()() as db:
        run = claim_next(db, "old-runtime-worker")
        assert run.id == created.json()["run"]["id"]
        transition(db, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(db, run, RunStatus.RUNNING, event_type="executor.started")
        run.metadata_json = {"dispatch_attempted": True}
        run.lease_expires_at = utcnow() - timedelta(seconds=2)
        db.add(ResourceLock(resource_key="ram:" + run.id, run_id=run.id))
        RunnerClient().prepare_runtime(payload(run))
        db.commit()
        return run.id


def test_stale_worker_reattaches_same_native_run_without_repeating_a_pull(runtime_catalog, bridge):
    with TestClient(app) as api:
        identity = dispatched(api, runtime_catalog, bridge)
        assert work() == identity
        value = api.get("/api/runs/" + identity).json()
        assert value["status"] == "succeeded", value
        assert len(bridge["requests"]) == 2 and bridge["requests"][0] == bridge["requests"][1]
        assert len(bridge["starts"]) == 1


def test_canceling_a_requeued_dispatched_run_still_confirms_native_stop(runtime_catalog, bridge):
    with TestClient(app) as api:
        identity = dispatched(api, runtime_catalog, bridge)
        with control_session_factory()() as db:
            recover_stale(db)
            db.commit()
            run = db.get(Run, identity)
            assert run.status == "queued"
            request_cancel(db, run)
            db.commit()
            assert run.status == "queued" and run.metadata_json["cancel_on_resume"]
        assert work() == identity
        assert api.get("/api/runs/" + identity).json()["status"] == "canceled"
        assert bridge["cancels"] and len(bridge["requests"]) == 1


def test_task_stop_just_before_publication_prevents_an_artifact(runtime_catalog, bridge):
    from app.task_control import cancel_task

    def stop(identity):
        with control_session_factory()() as db:
            run = db.get(Run, identity)
            cancel_task(db, run.task)
            db.commit()

    bridge["callback"] = stop
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()
        work()
        assert api.get("/api/runs/" + created["run"]["id"]).json()["status"] == "canceled"
        with control_session_factory()() as db:
            assert not list(db.scalars(select(Artifact)))


def test_inspection_required_retains_reservations_and_disables_resume(runtime_catalog, bridge):
    bridge["requires_inspection"] = True
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()
        work()
        value = api.get("/api/setup/runtimes/preparations/" + created["id"]).json()
        assert value["run"]["status"] == "interrupted" and value["resume_allowed"] is False
        with control_session_factory()() as db:
            assert any(row.released_at is None for row in db.scalars(select(ResourceLock)))
            assert not list(db.scalars(select(Artifact)))


def test_lost_claim_cannot_publish_or_release_new_workers_reservations(runtime_catalog, bridge):
    def take_claim(identity):
        with control_session_factory()() as db:
            run = db.get(Run, identity)
            run.worker_id = "new-runtime-worker"
            run.claimed_at = utcnow()
            db.commit()

    bridge["callback"] = take_claim
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()
        identity = created["run"]["id"]
        work()
        with control_session_factory()() as db:
            run = db.get(Run, identity)
            assert run.worker_id == "new-runtime-worker" and run.status == "running"
            assert "runtime_log_cursor" not in run.metadata_json
            assert not list(db.scalars(select(Artifact)))
            assert all(row.released_at is None for row in db.scalars(select(ResourceLock)))
        assert not bridge["cancels"]


def test_rejected_unaccepted_native_request_releases_resources(runtime_catalog, bridge, monkeypatch):
    def rejected(*args, **kwargs):
        raise RunnerError(409, "Synthetic unmet prerequisite")

    def missing(*args, **kwargs):
        raise RunnerError(404, "No accepted request")

    monkeypatch.setattr(RunnerClient, "prepare_runtime", rejected)
    monkeypatch.setattr(RunnerClient, "inspect_runtime_preparation", missing)
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()
        work()
        with control_session_factory()() as db:
            run = db.get(Run, created["run"]["id"])
            assert run.status == "failed" and run.metadata_json["process_confirmed_gone"]
            assert all(row.released_at for row in db.scalars(select(ResourceLock)))


def test_lost_start_response_reconciles_without_another_native_transfer(runtime_catalog, bridge, monkeypatch):
    original = RunnerClient.prepare_runtime

    def lost(self, value):
        original(self, value)
        monkeypatch.setattr(RunnerClient, "prepare_runtime", original)
        raise RunnerUnavailable("Synthetic lost acknowledgement")

    monkeypatch.setattr(RunnerClient, "prepare_runtime", lost)
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()
        identity = created["run"]["id"]
        work()
        with control_session_factory()() as db:
            run = db.get(Run, identity)
            assert run.status == "preparing"
            assert all(row.released_at is None for row in db.scalars(select(ResourceLock)))
        assert work() == identity
        assert api.get("/api/runs/" + identity).json()["status"] == "succeeded"
        assert len(bridge["starts"]) == 1 and bridge["requests"][0] == bridge["requests"][1]


def test_stop_during_hardware_inspection_never_sends_a_prepare_request(runtime_catalog, bridge, monkeypatch):
    def hardware(self):
        with control_session_factory()() as db:
            run = db.scalar(select(Run).where(Run.executor_type == "runtime_setup"))
            request_cancel(db, run)
            db.commit()
        return {"memory": {"available_mib": 16000}}

    monkeypatch.setattr(RunnerClient, "hardware", hardware)
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()
        work()
        assert api.get("/api/runs/" + created["run"]["id"]).json()["status"] == "canceled"
        assert not bridge["requests"] and bridge["cancels"]


def test_run_stop_while_start_acknowledgement_is_pending_is_preserved(runtime_catalog, bridge, monkeypatch):
    original = RunnerClient.prepare_runtime

    def stop(self, value):
        result = original(self, value)
        with control_session_factory()() as db:
            request_cancel(db, db.get(Run, value["run_id"]))
            db.commit()
        return result

    monkeypatch.setattr(RunnerClient, "prepare_runtime", stop)
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()
        work()
        assert api.get("/api/runs/" + created["run"]["id"]).json()["status"] == "canceled"
        assert bridge["cancels"] and len(bridge["starts"]) == 1
