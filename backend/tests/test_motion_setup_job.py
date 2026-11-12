"""Renderer activation keeps ordinary private setup, Stop and recovery contracts."""

from datetime import timedelta

import pytest
from app.api import app
from app.db import control_session_factory, utcnow
from app.model_setup import fingerprint
from app.models import Artifact, ResourceLock, Run, User
from app.motion_setup_client import PROFILE, MotionSetupClient
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import claim_next, transition
from app.runtime_setup_job import payload
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_runtime_setup_api import body
from test_runtime_setup_api import runtime_catalog as runtime_catalog
from test_runtime_setup_job import bridge as bridge
from test_runtime_setup_job import work


@pytest.fixture(autouse=True)
def motion(runtime_catalog, bridge, monkeypatch):
    recipe = runtime_catalog["recipe"]
    recipe.update(
        profile=PROFILE,
        preparation_mode="existing_image",
        image_reference="local:ai-station-motion:" + "c" * 64,
        download_bytes=0,
    )
    runtime_catalog.update(
        manifest_sha256=fingerprint(recipe),
        usable_image=True,
        renderer_observation="d" * 64,
        selected_image={
            "id": "sha256:" + "b" * 64,
            "reference": recipe["image_reference"],
            "platform": "linux/amd64",
        },
    )
    monkeypatch.setattr(MotionSetupClient, "runtime_setup_catalog", lambda _: runtime_catalog)
    monkeypatch.setattr(
        MotionSetupClient, "prepare_runtime", lambda self, value: RunnerClient.prepare_runtime(self, value)
    )
    monkeypatch.setattr(
        MotionSetupClient,
        "cancel_runtime_preparation",
        lambda self, identity, value: RunnerClient.cancel_runtime_preparation(self, identity, value),
    )

    def inspect(self, identity, **offsets):
        value = RunnerClient.inspect_runtime_preparation(self, identity, **offsets)
        return {**value, "renderer_observation": "d" * 64}

    monkeypatch.setattr(MotionSetupClient, "inspect_runtime_preparation", inspect)


def dispatched(api, catalog):
    response = api.post("/api/setup/runtimes", json=body(catalog))
    assert response.status_code == 202, response.text
    with control_session_factory()() as db:
        run = claim_next(db, "old-setup-worker")
        assert run.id == response.json()["run"]["id"]
        transition(db, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(db, run, RunStatus.RUNNING, event_type="executor.started")
        run.metadata_json = {"dispatch_attempted": True}
        run.lease_expires_at = utcnow() - timedelta(seconds=2)
        db.add(ResourceLock(resource_key="ram:" + run.id, run_id=run.id))
        MotionSetupClient().prepare_runtime(payload(run))
        db.commit()
        return run.id


def test_queues_only_then_publishes_actual_selected_renderer(runtime_catalog, bridge):
    with TestClient(app) as api:
        request = body(runtime_catalog)
        created = api.post("/api/setup/runtimes", json=request)
        assert created.status_code == 202, created.text
        identity = created.json()["run"]["id"]
        assert created.json()["run"]["executor_type"] == "motion_setup" and not bridge["requests"]
        assert api.post("/api/setup/runtimes", json=request).json()["run"]["id"] == identity
        assert work() == identity
        result = api.get("/api/runs/" + identity).json()
        assert result["status"] == "succeeded" and result["summary"] == "Local Full-HD film export is ready."
        with control_session_factory()() as db:
            assert len(list(db.scalars(select(Artifact).where(Artifact.run_id == identity)))) == 1
            assert all(lock.released_at for lock in db.scalars(select(ResourceLock)))
        assert len(bridge["starts"]) == 1


def test_changed_renderer_cannot_publish_readiness(runtime_catalog, bridge):
    runtime_catalog["renderer_observation"] = "e" * 64
    with TestClient(app) as api:
        identity = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()["run"]["id"]
        work()
        assert api.get("/api/runs/" + identity).json()["status"] == "failed"
        with control_session_factory()() as db:
            assert not list(db.scalars(select(Artifact)))


def test_recovery_reobserves_the_same_native_activation(runtime_catalog, bridge):
    with TestClient(app) as api:
        identity = dispatched(api, runtime_catalog)
        assert work() == identity
        assert api.get("/api/runs/" + identity).json()["status"] == "succeeded"
        assert len(bridge["starts"]) == 1
        assert bridge["requests"][0] == bridge["requests"][1]


def test_lost_ack_keeps_reservations_until_native_reconciliation(runtime_catalog, bridge, monkeypatch):
    original = RunnerClient.prepare_runtime

    def lost(self, value):
        original(self, value)
        monkeypatch.setattr(RunnerClient, "prepare_runtime", original)
        raise RunnerUnavailable("Synthetic lost activation acknowledgement")

    monkeypatch.setattr(RunnerClient, "prepare_runtime", lost)
    with TestClient(app) as api:
        identity = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()["run"]["id"]
        work()
        with control_session_factory()() as db:
            assert db.get(Run, identity).status == "preparing"
            assert all(lock.released_at is None for lock in db.scalars(select(ResourceLock)))
        work()
        assert api.get("/api/runs/" + identity).json()["status"] == "succeeded"
        assert len(bridge["starts"]) == 1


def test_task_stop_before_completion_prevents_receipt(runtime_catalog, bridge):
    from app.task_control import cancel_task

    def stop(identity):
        with control_session_factory()() as db:
            cancel_task(db, db.get(Run, identity).task)
            db.commit()

    bridge["callback"] = stop
    with TestClient(app) as api:
        identity = api.post("/api/setup/runtimes", json=body(runtime_catalog)).json()["run"]["id"]
        work()
        assert api.get("/api/runs/" + identity).json()["status"] == "canceled"
        with control_session_factory()() as db:
            assert not list(db.scalars(select(Artifact)))


@pytest.mark.parametrize("field", ["is_admin", "enabled"])
def test_revoked_operator_only_cancels_existing_activation(accounts, runtime_catalog, bridge, field):
    owner, _, _ = accounts
    identity = dispatched(owner, runtime_catalog)
    with control_session_factory()() as db:
        setattr(db.get(User, db.get(Run, identity).owner_id), field, False)
        db.commit()
    assert work() == identity
    with control_session_factory()() as db:
        assert db.get(Run, identity).status == "canceled"
        assert all(lock.released_at for lock in db.scalars(select(ResourceLock)))
        assert not list(db.scalars(select(Artifact)))
    assert len(bridge["requests"]) == 1 and bridge["cancels"][0][0] == identity


def test_setup_history_and_action_remain_owner_private(accounts, runtime_catalog):
    owner, other, _ = accounts
    created = owner.post("/api/setup/runtimes", json=body(runtime_catalog))
    assert created.status_code == 202, created.text
    path = "/api/setup/runtimes/preparations/" + created.json()["id"]
    assert other.get(path).status_code == 404
    assert other.post("/api/setup/runtimes", json=body(runtime_catalog)).status_code == 403
    assert other.get("/api/setup/runtimes/preparations", params={"profile": PROFILE}).json() == []


def test_fresh_setup_accounts_for_serial_stage_and_supervisor_memory(runtime_catalog, bridge, monkeypatch):
    runtime_catalog["recipe"].update(
        preparation_mode="owned_containers", preparation_ram_mib=2304, download_size_known=False
    )
    runtime_catalog["manifest_sha256"] = fingerprint(runtime_catalog["recipe"])
    monkeypatch.setattr(MotionSetupClient, "hardware", lambda _: {"memory": {"available_mib": 2048}})
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(runtime_catalog))
        assert created.status_code == 202, created.text
        identity = created.json()["run"]["id"]
        assert created.json()["run"]["requested_resources"]["ram_mib"] == 2304
        assert work() == identity
        result = api.get("/api/runs/" + identity).json()
        assert result["status"] == "queued" and not bridge["starts"]


def test_fresh_progress_reports_real_stages_without_fabricated_download_bytes():
    from types import SimpleNamespace

    from app.motion_setup_job import MotionSetupExecutor

    run = SimpleNamespace(
        parameters={"recipe": {"preparation_mode": "owned_containers", "download_bytes": 0}}
    )
    executor = MotionSetupExecutor()
    assert executor.progress(run, {"type": "motion.prepare.progress", "phase": "sdk"}) == {
        "phase": "sdk",
        "download_size_known": False,
    }
    assert executor.progress(run, {"type": "motion.prepare.progress", "phase": "made-up"}) is None
