"""A stale downloader cannot change a recovered worker's Run or reservations."""

from datetime import timedelta

import pytest
from app import model_download_job as job
from app.api import app
from app.db import control_session_factory, utcnow
from app.model_download_files import DownloadBusy
from app.models import Artifact, ModelFile, ResourceLock, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_model_setup import request, work
from test_model_setup import setup_bridge as setup_bridge


@pytest.mark.parametrize("same_worker", [False, True])
@pytest.mark.parametrize("boundary", ["progress", "publication", "deferral", "failure"])
def test_lost_download_claim_never_cancels_publishes_or_releases_new_owners_resources(
    setup_bridge, monkeypatch, boundary, same_worker
):
    state = {}

    def transfer():
        assert not state.get("transferred")
        with control_session_factory()() as db:
            run = db.get(Run, state["run_id"])
            state["worker"] = run.worker_id if same_worker else "recovered-worker"
            run.worker_id = state["worker"]
            run.claimed_at = utcnow() + timedelta(seconds=1)
            run.lease_expires_at = utcnow() + timedelta(minutes=5)
            state["claim"] = run.claimed_at
            for lock in db.scalars(select(ResourceLock).where(ResourceLock.run_id == run.id)):
                lock.released_at = utcnow()
            db.flush()
            lock = ResourceLock(resource_key="ram:" + run.id, run_id=run.id)
            db.add(lock)
            db.flush()
            state["lock_id"] = lock.id
            db.commit()
        state["transferred"] = True

    original = job.obtain
    original_lock = job.lock_task

    async def obtain(root, spec, *, check, progress):
        if boundary == "failure":
            transfer()
            raise ValueError("The old worker's transfer connection ended")
        if boundary == "deferral":
            transfer()
            raise DownloadBusy()

        def report(received, total):
            if boundary == "progress":
                transfer()
            progress(received, total)

        return await original(root, spec, check=check, progress=report)

    def publication_lock(session, task):
        if boundary == "publication":
            # Release preparation reads before the other worker claims and
            # the old worker enters its publication transaction.
            session.rollback()
            transfer()
        return original_lock(session, task)

    monkeypatch.setattr(job, "obtain", obtain)
    monkeypatch.setattr(job, "lock_task", publication_lock)
    with TestClient(app) as api:
        created = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        assert created.status_code == 202
        state["run_id"] = created.json()["run"]["id"]
        work()
        assert state.get("transferred"), api.get("/api/runs/" + state["run_id"]).json()["error_message"]
        with control_session_factory()() as db:
            run = db.get(Run, state["run_id"])
            assert run.status == "running" and run.worker_id == state["worker"]
            assert run.claimed_at == state["claim"] and run.cancellation_requested_at is None
            assert db.get(ResourceLock, state["lock_id"]).released_at is None
            assert list(db.scalars(select(Artifact).where(Artifact.run_id == run.id))) == []
            assert list(db.scalars(select(ModelFile))) == []
