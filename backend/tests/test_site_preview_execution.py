import hashlib
import io
import time
from uuid import uuid4

import pytest
from app.api import app
from app.config import get_settings
from app.engine import tick
from app.models import Artifact, ResourceLock, Run
from app.runs import create_run, create_task, transition
from app.site_preview import PERMISSIONS
from app.site_preview_executor import adopt_frame
from app.state import RunStatus
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from test_site_preview_provenance import built


class Peer:
    def __init__(self):
        self.requests = []
        self.processes = {}
        self.frames = {}
        self.polls = {}
        self.memory = 20480
        self.cleanup = True
        self.reject = False

    def hardware(self):
        return {"memory": {"available_mib": self.memory}, "gpus": []}

    def frame(self, parent_id, revision=0, action_id=None):
        record = self.processes[parent_id]
        data = io.BytesIO()
        Image.new(
            "RGB", (record["width"], record["height"]), color="white" if revision == 0 else "blue"
        ).save(data, format="PNG")
        value = data.getvalue()
        relative = f"runtime/site-previews/{parent_id}/frames/{revision}.png"
        file = get_settings().data_dir / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value)
        return {
            "revision": revision,
            "action_id": action_id,
            "width": record["width"],
            "height": record["height"],
            "path": "index.html",
            "title": "Disposable preview",
            "blocked_requests": 0,
            "relative_path": relative,
            "size_bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        if path == "/v1/site-preview/capabilities":
            return {
                "available": True,
                "protocol": 2,
                "network": False,
                "gpu": False,
                "maximum_sessions": 1,
                "runner_id": "local",
            }
        if method == "POST" and path == "/v1/runs/site-preview":
            if self.reject:
                from app.runner_client import RunnerError

                raise RunnerError(409, "Uncertain preview dispatch")
            self.processes[body["run_id"]] = body
            self.frames[body["run_id"]] = self.frame(body["run_id"])
            return {
                "pid": 111,
                "process_group_id": 111,
                "runner_id": "local",
                "stdout_log": "logs/stdout.log",
                "stderr_log": "logs/stderr.log",
            }
        if method == "POST" and path == "/v1/runs/site-preview-action":
            self.processes[body["run_id"]] = body
            self.frames[body["preview_run_id"]] = self.frame(
                body["preview_run_id"], body["expected_revision"] + 1, body["run_id"]
            )
            return {
                "pid": 112,
                "process_group_id": 112,
                "runner_id": "local",
                "stdout_log": "logs/action.log",
                "stderr_log": "logs/action-error.log",
            }
        if path.endswith("/state"):
            parent_id = path.split("/")[-2]
            return {
                "frame": self.frames.get(parent_id),
                "expires_at": time.time() + 300,
                "cancel_requested": False,
            }
        if path.endswith("/close"):
            return {"cleanup_confirmed": self.cleanup}
        if "/site-preview-action/" in path and path.endswith("/report"):
            action_id = path.split("/")[-2]
            value = self.processes[action_id]
            return {"state": "frame", "frame": self.frames[value["preview_run_id"]]}
        if path.endswith("/report"):
            return {"reason": "expired"}
        raise AssertionError((method, path))

    def inspect_process(self, run_id, **offsets):
        self.polls[run_id] = self.polls.get(run_id, 0) + 1
        return {
            "alive": self.polls[run_id] < 2,
            "status": "exited",
            "exit_code": 0,
            "cleanup_confirmed": True,
            "stdout": "",
            "stderr": "",
            "stdout_offset": 0,
            "stderr_offset": 0,
            "stdout_more": False,
            "stderr_more": False,
        }

    def cancel_process(self, run_id):
        self.polls[run_id] = 3
        return self.inspect_process(run_id)


@pytest.fixture
def peer(monkeypatch):
    from app import native_job_executor, site_preview, site_preview_executor

    value = Peer()
    monkeypatch.setenv("AI_STATION_SITE_PREVIEW_ENABLED", "true")
    from app.config import clear_settings_cache

    clear_settings_cache()
    for module in (native_job_executor, site_preview, site_preview_executor):
        monkeypatch.setattr(module, "RunnerClient", lambda *args, **kwargs: value)
    return value


def open_body(session):
    source, artifact = built(session)
    session.commit()
    return {"client_request_id": str(uuid4()), "source_run_id": source.id, "artifact_id": artifact.id}, source


def test_open_replay_and_single_session_only_enqueue_without_native_execution(session, peer):
    body, source = open_body(session)
    with TestClient(app) as client:
        first = client.post("/api/site-previews", json=body)
        assert first.status_code == 202, first.text
        replay = client.post("/api/site-previews", json=body)
        assert replay.json()["id"] == first.json()["id"]
        assert client.post("/api/site-previews", json={**body, "width": 390}).status_code == 409
        assert (
            client.post("/api/site-previews", json={**body, "client_request_id": str(uuid4())}).status_code
            == 409
        )
        row = session.get(Run, first.json()["id"])
        assert row.task_id != source.task_id and row.project_id == source.project_id and row.agent_id is None
        assert row.effective_permissions == list(PERMISSIONS) and row.requested_gpu == "none"
        assert row.status == "queued" and not any(method == "POST" for method, _, _ in peer.requests)
        session.commit()
        assert (
            client.get("/api/site-previews", params={"source_task_id": source.task_id}).json()[0]["id"]
            == row.id
        )


def test_worker_reserves_cpu_ram_and_adopts_audited_immutable_frames(session, peer):
    body, _ = open_body(session)
    with TestClient(app) as client:
        run_id = client.post("/api/site-previews", json=body).json()["id"]
        assert tick(session, "preview-worker") == run_id
        session.expire_all()
        run = session.get(Run, run_id)
        assert run.status == "succeeded" and run.metadata_json["process_confirmed_gone"]
        assert run.allocated_resources["ram_mib"] == 1536 and run.allocated_resources["gpu"] == "none"
        frame = run.metadata_json["frame"]
        artifact = session.get(Artifact, frame["artifact_id"])
        assert artifact.run_id == run.id and artifact.parent_artifact_ids == [body["artifact_id"]]
        assert artifact.relative_path.startswith("artifacts/") and frame["revision"] == 0
        session.commit()
        assert client.get(f"/api/artifacts/{artifact.id}/file").status_code == 200
        assert not session.scalar(
            select(ResourceLock).where(ResourceLock.run_id == run_id, ResourceLock.released_at.is_(None))
        )


def test_low_ram_defers_only_preview_and_allows_unrelated_work(session, peer):
    peer.memory = 0
    body, _ = open_body(session)
    with TestClient(app) as client:
        run_id = client.post("/api/site-previews", json=body).json()["id"]
        assert tick(session, "low-memory") == run_id
        session.refresh(session.get(Run, run_id))
        assert session.get(Run, run_id).status == "queued"
        task = create_task(session, title="Other work", prompt="", capability="test")
        other = create_run(
            session,
            task,
            run_type="test",
            capability="test",
            executor_type="fake",
            execution_target="container",
        )
        session.commit()
        assert tick(session, "other-worker") == other.id
        assert not any(method == "POST" for method, _, _ in peer.requests)


def test_uncertain_native_rejection_retains_locks_until_close_confirms_cleanup(session, peer):
    peer.reject = True
    peer.cleanup = False
    body, _ = open_body(session)
    with TestClient(app) as client:
        run_id = client.post("/api/site-previews", json=body).json()["id"]
        tick(session, "rejected-worker")
        session.expire_all()
        parent = session.get(Run, run_id)
        assert parent.status == "interrupted" and parent.metadata_json["cleanup_requires_inspection"]
        assert session.scalar(
            select(ResourceLock).where(ResourceLock.run_id == run_id, ResourceLock.released_at.is_(None))
        )
        session.commit()
        close = client.post(
            f"/api/site-previews/{run_id}/close", json={"client_request_id": str(uuid4())}
        ).json()
        tick(session, "close-unconfirmed")
        session.expire_all()
        assert session.get(Run, close["id"]).status == "interrupted"
        assert session.scalar(
            select(ResourceLock).where(ResourceLock.run_id == run_id, ResourceLock.released_at.is_(None))
        )
        session.commit()
        peer.cleanup = True
        closed = client.post(
            f"/api/site-previews/{run_id}/close", json={"client_request_id": str(uuid4())}
        ).json()
        tick(session, "close-confirmed")
        session.expire_all()
        assert session.get(Run, closed["id"]).status == "succeeded"
        assert not session.scalar(
            select(ResourceLock).where(ResourceLock.run_id == run_id, ResourceLock.released_at.is_(None))
        )


def test_action_preserves_task_revision_and_cannot_publish_after_stop(session, peer):
    body, _ = open_body(session)
    with TestClient(app) as client:
        parent_id = client.post("/api/site-previews", json=body).json()["id"]
        parent = session.get(Run, parent_id)
        transition(session, parent, RunStatus.CLAIMED, event_type="test.claim")
        transition(session, parent, RunStatus.PREPARING, event_type="test.prepare")
        transition(session, parent, RunStatus.RUNNING, event_type="test.start")
        peer.processes[parent_id] = {"width": 1240, "height": 800}
        initial = peer.frame(parent_id)
        adopt_frame(session, parent, initial)
        session.commit()
        request = {
            "client_request_id": str(uuid4()),
            "expected_revision": 0,
            "action": {"kind": "click", "x": 20, "y": 30},
        }
        posted = client.post(f"/api/site-previews/{parent_id}/actions", json=request)
        assert posted.status_code == 202, posted.text
        action_id = posted.json()["id"]
        assert client.post(f"/api/site-previews/{parent_id}/actions", json=request).json()["id"] == action_id
        assert (
            client.post(
                f"/api/site-previews/{parent_id}/actions", json={**request, "client_request_id": str(uuid4())}
            ).status_code
            == 409
        )
        tick(session, "action-worker")
        session.expire_all()
        action = session.get(Run, action_id)
        parent = session.get(Run, parent_id)
        assert action.status == "succeeded" and action.task_id == parent.task_id
        assert (
            parent.metadata_json["frame"]["revision"] == 1
            and action.metadata_json["frame_artifact_id"] == parent.metadata_json["frame"]["artifact_id"]
        )
        session.commit()
        assert (
            client.post(
                f"/api/site-previews/{parent_id}/actions", json={**request, "client_request_id": str(uuid4())}
            ).status_code
            == 409
        )
        close_request = {"client_request_id": str(uuid4())}
        closed = client.post(f"/api/site-previews/{parent_id}/close", json=close_request)
        assert closed.status_code == 202
        assert (
            client.post(f"/api/site-previews/{parent_id}/close", json=close_request).json()["id"]
            == closed.json()["id"]
        )
        assert (
            client.post(
                f"/api/site-previews/{parent_id}/actions",
                json={**request, "client_request_id": str(uuid4()), "expected_revision": 1},
            ).status_code
            == 409
        )
        tick(session, "close-worker")
        session.expire_all()
        assert session.get(Run, parent_id).metadata_json["closed_at"]
        with pytest.raises(InterruptedError):
            adopt_frame(session, session.get(Run, parent_id), initial)


@pytest.mark.parametrize("cleanup", [False, None, True])
def test_preview_recovery_preserves_uncertain_reservations_without_replaying(session, peer, cleanup):
    from datetime import timedelta

    from app.db import utcnow
    from app.recovery import recover_stale

    body, _ = open_body(session)
    with TestClient(app) as client:
        run_id = client.post("/api/site-previews", json=body).json()["id"]
    run = session.get(Run, run_id)
    transition(session, run, RunStatus.CLAIMED, event_type="test.claim")
    transition(session, run, RunStatus.PREPARING, event_type="test.prepare")
    run.metadata_json = {"dispatch_attempted": True}
    run.lease_expires_at = utcnow() - timedelta(seconds=60)
    session.add(ResourceLock(resource_key="site-preview:local", run_id=run_id))
    session.commit()

    class RecoveryPeer:
        def inspect_process(self, rid):
            assert rid == run_id
            return {"alive": False, "cleanup_confirmed": cleanup}

    assert recover_stale(session, RecoveryPeer()) == [run_id]
    session.refresh(run)
    assert run.status == "interrupted"
    held = session.scalar(
        select(ResourceLock).where(ResourceLock.run_id == run_id, ResourceLock.released_at.is_(None))
    )
    assert bool(held) == (cleanup is not True)
    assert not any(method == "POST" for method, _, _ in peer.requests)
