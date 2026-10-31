"""Bundle authority, cancellation and claim epochs cover the real queue/API."""

from datetime import timedelta

import pytest
from app import bundle_download_job as job
from app.api import app
from app.db import control_session_factory, utcnow
from app.model_download_files import DownloadBusy
from app.models import Artifact, ModelFile, ResourceLock, Run, User
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_model_bundles import body, work
from test_model_bundles import bundle_source as bundle_source


def test_bundle_history_and_receipts_private_while_model_files_shared(accounts, bundle_source):
    owner, alice, bob = accounts
    request = body(bundle_source["entry"])
    assert alice.post("/api/setup/bundles/downloads", json=request).status_code == 403
    created = owner.post("/api/setup/bundles/downloads", json=request)
    assert created.status_code == 202, created.text
    identity, run_id = created.json()["id"], created.json()["run"]["id"]
    assert alice.get("/api/setup/bundles/downloads").json() == []
    assert bob.get("/api/setup/bundles/downloads/" + identity).status_code == 404
    assert alice.post("/api/setup/bundles/downloads/" + identity + "/cancel").status_code == 403
    assert not bob.get("/api/setup/bundles/catalog").json()["can_prepare"]
    work()
    value = owner.get("/api/setup/bundles/downloads/" + identity).json()
    assert value["run"]["status"] == "succeeded", value["run"]["error_message"]
    assert bob.get("/api/runs/" + run_id).status_code == 404
    for model_id in value["model_file_ids"]:
        assert bob.get("/api/models/" + model_id).status_code == 200
    with control_session_factory()() as db:
        artifact = db.scalar(select(Artifact).where(Artifact.run_id == run_id))
        artifact_id = artifact.id
    assert bob.get("/api/artifacts/" + artifact_id + "/file").status_code == 404
    assert owner.get("/api/artifacts/" + artifact_id + "/file").status_code == 200


@pytest.mark.parametrize("field", ["is_admin", "enabled"])
def test_revoked_administrator_cannot_finish_bundle(accounts, bundle_source, field):
    owner, _, _ = accounts
    created = owner.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()

    def demote(name):
        with control_session_factory()() as db:
            run = db.get(Run, created["run"]["id"])
            setattr(db.get(User, run.owner_id), field, False)
            db.commit()
        bundle_source["hook"] = None

    bundle_source["hook"] = demote
    work()
    with control_session_factory()() as db:
        assert db.get(Run, created["run"]["id"]).status == "canceled"
        assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))
        assert not list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


@pytest.mark.parametrize("same_worker", [False, True])
@pytest.mark.parametrize("boundary", ["progress", "publication", "deferral", "failure"])
def test_stale_bundle_worker_never_mutates_replacement(bundle_source, monkeypatch, boundary, same_worker):
    state = {}

    def transfer():
        assert not state.get("transferred")
        with control_session_factory()() as db:
            run = db.get(Run, state["run_id"])
            run.worker_id = run.worker_id if same_worker else "replacement-worker"
            run.claimed_at = utcnow() + timedelta(seconds=1)
            run.lease_expires_at = utcnow() + timedelta(minutes=5)
            state.update(worker=run.worker_id, claim=run.claimed_at)
            for lock in db.scalars(select(ResourceLock).where(ResourceLock.run_id == run.id)):
                lock.released_at = utcnow()
            db.flush()
            lock = ResourceLock(resource_key="ram:" + run.id, run_id=run.id)
            db.add(lock)
            db.flush()
            state["lock_id"] = lock.id
            db.commit()
        state["transferred"] = True

    original, original_lock = job.obtain, job.lock_task

    async def obtain(root, spec, *, check, progress):
        if boundary in {"failure", "deferral"}:
            transfer()
            raise DownloadBusy() if boundary == "deferral" else ValueError("Old transfer ended")
        return await original(root, spec, check=check, progress=progress)

    def publication(session, task):
        if boundary == "publication":
            session.rollback()
            transfer()
        return original_lock(session, task)

    if boundary == "progress":
        bundle_source["hook"] = lambda _: transfer()
    monkeypatch.setattr(job, "obtain", obtain)
    monkeypatch.setattr(job, "lock_task", publication)
    with TestClient(app) as api:
        created = api.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()
        state["run_id"] = created["run"]["id"]
        work()
        assert state.get("transferred")
        with control_session_factory()() as db:
            run = db.get(Run, state["run_id"])
            assert run.status == "running" and run.worker_id == state["worker"]
            assert run.claimed_at == state["claim"] and run.cancellation_requested_at is None
            assert db.get(ResourceLock, state["lock_id"]).released_at is None
            assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))


def test_stop_serializes_with_whole_bundle_publication(bundle_source, monkeypatch):
    original = job.lock_task
    with TestClient(app) as api:
        created = api.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()

        def stop(session, task):
            session.rollback()
            result = api.post("/api/setup/bundles/downloads/" + created["id"] + "/cancel")
            assert result.status_code == 200
            return original(session, task)

        monkeypatch.setattr(job, "lock_task", stop)
        work()
        assert api.get("/api/runs/" + created["run"]["id"]).json()["status"] == "canceled"
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))


def test_waiting_for_an_object_preserves_verified_progress_and_cached_files(bundle_source, monkeypatch):
    from app.models import Task
    from app.resources import RESOURCE_WAIT_KEY

    original = job.obtain

    async def busy(root, spec, **kwargs):
        if spec == bundle_source["entry"].files[-1].file:
            raise DownloadBusy()
        return await original(root, spec, **kwargs)

    monkeypatch.setattr(job, "obtain", busy)
    with TestClient(app) as api:
        created = api.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()
        work()
        value = api.get("/api/setup/bundles/downloads/" + created["id"]).json()
        assert value["run"]["status"] == "queued"
        assert value["progress"]["completed_files"] == 2
        assert value["progress"]["phase"] == "waiting_for_existing_transfer"
        assert value["progress"]["verified_bytes"] == sum(
            v.file.size_bytes for v in bundle_source["entry"].files[:2]
        )
        with control_session_factory()() as db:
            task = db.get(Task, created["id"])
            task.metadata_json = {k: v for k, v in task.metadata_json.items() if k != RESOURCE_WAIT_KEY}
            assert not list(db.scalars(select(ModelFile)))
            db.commit()
        monkeypatch.setattr(job, "obtain", original)
        work()
        assert api.get("/api/setup/bundles/downloads/" + created["id"]).json()["run"]["status"] == "succeeded"
        assert len(bundle_source["calls"]) == 3


def test_verified_object_changed_before_publication_is_not_registered(bundle_source, monkeypatch):
    from app.config import get_settings

    original = job.lock_task

    def changed(session, task):
        path = get_settings().data_dir / "models/store" / bundle_source["entry"].files[0].file.sha256
        path.chmod(0o600)
        path.write_bytes(b"changed object")
        path.chmod(0o444)
        return original(session, task)

    monkeypatch.setattr(job, "lock_task", changed)
    with TestClient(app) as api:
        value = api.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()
        work()
        assert api.get("/api/runs/" + value["run"]["id"]).json()["status"] == "failed"
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))


def test_effective_download_permission_is_required_before_any_transfer(bundle_source):
    with TestClient(app) as api:
        created = api.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()
        with control_session_factory()() as db:
            run = db.get(Run, created["run"]["id"])
            run.effective_permissions = [v for v in run.effective_permissions if v != "network_read"]
            db.commit()
        work()
        assert api.get("/api/runs/" + created["run"]["id"]).json()["status"] == "failed"
        assert not bundle_source["calls"]
