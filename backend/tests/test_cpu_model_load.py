"""CPU queue/admission/recovery use real domain state with a fake native process."""

from datetime import timedelta

import pytest
from app.api import app
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import ModelDefinition, ResourceLock, Run
from app.recovery import recover_stale
from app.runner_client import RunnerClient, RunnerUnavailable
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_model_setup import request as download_request
from test_model_setup import setup_bridge as setup_bridge


@pytest.fixture
def cpu_ready(setup_bridge, monkeypatch):
    state = {"loads": [], "status": "ready", "free": 30000, "lose_ack": False}
    hardware = setup_bridge["hardware"]
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {**hardware, "memory": {**hardware["memory"], "available_mib": state["free"]}},
    )

    def observe(*_args):
        return {
            "status": state["status"],
            "alive": state["status"] == "ready",
            "n_ctx": 4096,
            "container_id": "a" * 64,
        }

    def load(_, body):
        state["loads"].append(body)
        assert body["runtime_profile"] == setup_bridge["entry"].runtime_profile
        if state["lose_ack"]:
            state["lose_ack"] = False
            raise RunnerUnavailable("Synthetic lost native acknowledgment")
        return observe()

    def stop(*_args):
        state["status"] = "stopped"
        return observe()

    monkeypatch.setattr(RunnerClient, "load_llama", load)
    monkeypatch.setattr(RunnerClient, "inspect_llama", observe)
    monkeypatch.setattr(RunnerClient, "stop_llama", stop)
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json=download_request(setup_bridge["entry"]))
        assert response.status_code == 202
        work()
        with control_session_factory()() as db:
            definition = db.scalar(select(ModelDefinition))
            assert definition is not None and definition.status == "registered"
            did = definition.id
        queued = api.post("/api/models/definitions/" + did + "/load", json={})
        assert queued.status_code == 202, queued.text
        yield api, queued.json(), state


def work():
    with control_session_factory()() as db:
        return tick(db, "cpu-test-worker")


@pytest.mark.parametrize("setup_bridge", ["cpu"], indirect=True)
def test_cpu_ready_retains_ram_until_confirmed_owned_stop(cpu_ready):
    api, queued, state = cpu_ready
    work()
    result = api.get("/api/runs/" + queued["id"]).json()
    assert result["status"] == "succeeded", result["error_message"]
    assert result["allocated_resources"]["gpus"] == []
    assert result["allocated_resources"]["ram_mib"] == queued["parameters"]["ram_mib"]
    with control_session_factory()() as db:
        locks = list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
        assert [lock.resource_key for lock in locks] == ["ram:" + queued["id"]]
    assert len(state["loads"]) == 1
    stopped = api.post("/api/llama/" + queued["parameters"]["instance_id"] + "/stop", json={})
    assert stopped.status_code == 202
    work()
    assert api.get("/api/runs/" + stopped.json()["id"]).json()["status"] == "succeeded"
    with control_session_factory()() as db:
        assert list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None)))) == []


@pytest.mark.parametrize("setup_bridge", ["cpu"], indirect=True)
def test_cpu_waits_for_available_ram_without_dispatch(cpu_ready):
    api, queued, state = cpu_ready
    state["free"] = 256
    work()
    run = api.get("/api/runs/" + queued["id"]).json()
    assert run["status"] == "queued" and run["resource_wait"]["reason"] == "memory"
    assert not state["loads"]
    assert api.post("/api/runs/" + queued["id"] + "/cancel", json={}).status_code == 200


@pytest.mark.parametrize("setup_bridge", ["cpu"], indirect=True)
def test_cpu_lost_ack_reattaches_frozen_request_even_when_free_ram_falls(cpu_ready):
    api, queued, state = cpu_ready
    state["lose_ack"] = True
    work()
    with control_session_factory()() as db:
        row = db.get(Run, queued["id"])
        assert row.metadata_json["dispatch_attempted"]
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        assert queued["id"] in recover_stale(db)
        db.commit()
    state["free"] = 256
    work()
    result = api.get("/api/runs/" + queued["id"]).json()
    assert result["status"] == "succeeded", result["error_message"]
    assert len(state["loads"]) == 2 and state["loads"][0] == state["loads"][1]
