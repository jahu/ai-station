"""Real account/API/worker/download path with tiny inputs and a fake native SDK."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from app import runtime_setup_api
from app.api import app
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import Artifact, ModelFile, ResourceLock, Run, User
from app.video_setup_client import VideoSetupClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_model_bundles import bundle_source as bundle_source


@pytest.fixture
def video_source(bundle_source, monkeypatch):
    entry = bundle_source["entry"]
    recipe = {
        "profile": runtime_setup_api.VIDEO_PROFILE,
        "model_revision": entry.revision,
        "model_license_url": entry.license_url,
        "model_repository": entry.repository,
        "inputs": [],
    }
    import hashlib

    payloads = bundle_source["payloads"]
    payloads.update({"python.bin": b"python runtime", "sdk.bin": b"SDK source", "wheel.bin": b"fixed wheel"})
    kinds = {"python.bin": "python", "sdk.bin": "sdk", "wheel.bin": "wheel"}
    recipe["inputs"] = [
        dict(
            kind=kinds.get(name, "model"),
            filename=name,
            sha256=hashlib.sha256(value).hexdigest(),
            size_bytes=len(value),
            url="https://models.example.com/pinned/" + name,
        )
        for name, value in payloads.items()
    ]
    state = {
        "recipe": recipe,
        "manifest_sha256": runtime_setup_api.fingerprint(recipe),
        "starts": [],
        "cancels": [],
        "adoptions": [],
        "at_start": None,
    }
    monkeypatch.setattr(
        VideoSetupClient,
        "runtime_setup_catalog",
        lambda _: {
            "recipe": state["recipe"],
            "manifest_sha256": state["manifest_sha256"],
            "installation_available": True,
        },
    )

    def prepare(_, payload):
        state["starts"].append(payload)
        if state["at_start"]:
            state["at_start"](payload)
        return {
            "run_id": payload["run_id"],
            "manifest_sha256": payload["manifest_sha256"],
            "status": "running",
            "alive": True,
            "requires_inspection": False,
        }

    def inspect(_, identity, *, stdout_offset=0, stderr_offset=0):
        log = json.dumps({"video_preparation": {"phase": "installing_dependencies"}}) + "\n"
        return {
            "run_id": identity,
            "manifest_sha256": state["starts"][-1]["manifest_sha256"],
            "status": "succeeded",
            "alive": False,
            "requires_inspection": False,
            "environment_prepared": True,
            "process": {
                "pid": 123,
                "process_group_id": 123,
                "stdout_log": f"runs/{identity}/stdout.log",
                "stderr_log": f"runs/{identity}/stderr.log",
                "stdout": log if stdout_offset == 0 else "",
                "stderr": "",
                "stdout_offset": len(log),
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
            },
        }

    def cancel(_, identity, payload):
        state["cancels"].append(identity)
        return {
            "run_id": identity,
            "manifest_sha256": None,
            "status": "canceled",
            "alive": False,
            "requires_inspection": False,
            "process": None,
        }

    def adopt(_, identity, payload):
        state["adoptions"].append(identity)
        return {
            "operation_id": identity,
            "manifest_sha256": state["starts"][-1]["manifest_sha256"],
            "profile": runtime_setup_api.VIDEO_PROFILE,
            "environment_prepared": True,
            "video_inference_tested_now": False,
        }

    monkeypatch.setattr(VideoSetupClient, "prepare_runtime", prepare)
    monkeypatch.setattr(VideoSetupClient, "inspect_runtime_preparation", inspect)
    monkeypatch.setattr(VideoSetupClient, "cancel_runtime_preparation", cancel)
    monkeypatch.setattr(VideoSetupClient, "adopt_video_environment", adopt)
    state["source"] = bundle_source
    return state


def body(source):
    return {
        "client_request_id": str(uuid4()),
        "profile": runtime_setup_api.VIDEO_PROFILE,
        "manifest_sha256": source["manifest_sha256"],
        "license_accepted": True,
    }


def work():
    with control_session_factory()() as session:
        return tick(session, "video-worker")


def test_complete_video_install_uses_owned_queue_verified_inputs_and_native_supervisor(video_source):
    with TestClient(app) as api:
        request = body(video_source)
        catalog = api.get("/api/setup/runtimes", params={"profile": request["profile"]})
        assert catalog.status_code == 200 and catalog.json()["installation_available"]
        created = api.post("/api/setup/runtimes", json=request)
        assert created.status_code == 202, created.text
        value = created.json()
        assert not video_source["starts"] and not video_source["source"]["calls"]
        assert value["run"]["executor_type"] == "video_setup"
        assert value["run"]["requested_resources"]["ram_mib"] == 4096
        assert api.post("/api/setup/runtimes", json=request).json()["id"] == value["id"]
        work()
        completed = api.get("/api/setup/runtimes/preparations/" + value["id"]).json()
        assert completed["run"]["status"] == "succeeded", api.get(
            "/api/runs/" + completed["run"]["id"] + "/events"
        ).json()[-1]["payload"]
        assert completed["progress"]["phase"] == "environment_prepared"
        assert completed["progress"]["video_inference_tested"] is False
        assert video_source["adoptions"] == [completed["run"]["id"]]
        assert api.get("/api/setup/runtimes/preparations").json() == []
        assert (
            len(api.get("/api/setup/runtimes/preparations", params={"profile": request["profile"]}).json())
            == 1
        )
        with control_session_factory()() as session:
            assert len(list(session.scalars(select(ModelFile)))) == 3
            assert len(list(session.scalars(select(Artifact)))) == 1
            assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
        assert "runtime.video.prepared" in api.get("/api/runs/" + completed["run"]["id"] + "/stream").text


def test_corrupt_input_never_starts_or_publishes_a_video_environment(video_source):
    video_source["source"]["corrupt"] = True
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(video_source)).json()
        work()
        result = api.get("/api/runs/" + created["run"]["id"]).json()
        assert result["status"] == "failed"
        assert not video_source["starts"] and not video_source["adoptions"]
        with control_session_factory()() as session:
            assert not list(session.scalars(select(ModelFile))) and not list(
                session.scalars(select(Artifact))
            )
            assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


def test_stop_and_resume_keep_download_bytes_and_original_manifest(video_source):
    source = video_source["source"]
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(video_source)).json()
        original = video_source["recipe"]

        def stop(name):
            if name == "weights.safetensors":
                source["hook"] = None
                api.post("/api/setup/runtimes/preparations/" + created["id"] + "/cancel").raise_for_status()

        source["hook"] = stop
        work()
        current = api.get("/api/setup/runtimes/preparations/" + created["id"]).json()
        assert current["run"]["status"] == "canceled" and not video_source["starts"]
        video_source["recipe"] = {"profile": "unavailable new catalog"}
        resumed = api.post(
            "/api/setup/runtimes/preparations/" + created["id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": current["run"]["id"]},
        )
        assert resumed.status_code == 202, resumed.text
        work()
        current = api.get("/api/setup/runtimes/preparations/" + created["id"]).json()
        assert current["run"]["status"] == "succeeded", current["run"]["error_message"]
        assert current["recipe"] == original
        assert [name for name, _ in source["calls"]].count("encoder.pt") == 1


def test_stop_after_native_start_cannot_publish_shared_or_private_receipts(video_source):
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(video_source)).json()
        video_source["at_start"] = lambda _: api.post(
            "/api/setup/runtimes/preparations/" + created["id"] + "/cancel"
        ).raise_for_status()
        work()
        assert api.get("/api/runs/" + created["run"]["id"]).json()["status"] == "canceled"
        assert video_source["cancels"] and not video_source["adoptions"]
        with control_session_factory()() as session:
            assert not list(session.scalars(select(ModelFile))) and not list(
                session.scalars(select(Artifact))
            )


def test_private_video_setup_history_and_receipt_with_shared_model_files(accounts, video_source):
    owner, alice, bob = accounts
    assert alice.post("/api/setup/runtimes", json=body(video_source)).status_code == 403
    created = owner.post("/api/setup/runtimes", json=body(video_source)).json()
    assert bob.get("/api/setup/runtimes/preparations/" + created["id"]).status_code == 404
    work()
    completed = owner.get("/api/setup/runtimes/preparations/" + created["id"]).json()
    assert completed["run"]["status"] == "succeeded", owner.get(
        "/api/runs/" + completed["run"]["id"] + "/events"
    ).json()[-1]["payload"]
    with control_session_factory()() as session:
        artifact = session.scalar(select(Artifact))
        identity = artifact.id
        model_ids = list(session.scalars(select(ModelFile.id)))
    assert bob.get("/api/artifacts/" + identity + "/file").status_code == 404
    assert owner.get("/api/artifacts/" + identity + "/file").status_code == 200
    assert all(bob.get("/api/models/" + identity).status_code == 200 for identity in model_ids)


@pytest.mark.parametrize("same_worker", [False, True])
@pytest.mark.parametrize("boundary", ["download", "dispatch", "publication", "failure"])
def test_stale_video_setup_cannot_publish_or_release_replacement(
    video_source, monkeypatch, boundary, same_worker
):
    from app import runtime_setup_job

    state = {}

    def transfer():
        with control_session_factory()() as session:
            run = session.get(Run, state["id"])
            run.worker_id = run.worker_id if same_worker else "replacement-video-worker"
            run.claimed_at = utcnow() + timedelta(seconds=1)
            run.lease_expires_at = utcnow() + timedelta(minutes=5)
            state.update(worker=run.worker_id, claim=run.claimed_at)
            for row in session.scalars(select(ResourceLock).where(ResourceLock.run_id == run.id)):
                row.released_at = utcnow()
            session.flush()
            lock = ResourceLock(resource_key="ram:" + run.id, run_id=run.id)
            session.add(lock)
            session.flush()
            state["lock"] = lock.id
            session.commit()

    def dispatched(payload):
        transfer()
        if boundary == "failure":
            raise ValueError("Synthetic old native request failure")

    if boundary == "download":
        video_source["source"]["hook"] = lambda _: transfer()
    elif boundary in {"dispatch", "failure"}:
        video_source["at_start"] = dispatched
    else:
        original = runtime_setup_job.lock_task

        def before_publication(session, task):
            session.rollback()
            transfer()
            return original(session, task)

        monkeypatch.setattr(runtime_setup_job, "lock_task", before_publication)
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(video_source)).json()
        state["id"] = created["run"]["id"]
        work()
        with control_session_factory()() as session:
            run = session.get(Run, state["id"])
            assert run.worker_id == state["worker"] and run.claimed_at == state["claim"]
            assert run.status not in {"succeeded", "failed", "canceled"}
            assert session.get(ResourceLock, state["lock"]).released_at is None
            assert not list(session.scalars(select(ModelFile))) and not list(
                session.scalars(select(Artifact))
            )
        assert not video_source["adoptions"]


@pytest.mark.parametrize("field", ["enabled", "is_admin"])
def test_revoked_video_setup_authority_only_cancels_owned_native_action(accounts, video_source, field):
    owner, _, _ = accounts
    created = owner.post("/api/setup/runtimes", json=body(video_source)).json()
    identity = created["run"]["id"]

    def revoke(payload):
        with control_session_factory()() as session:
            run = session.get(Run, identity)
            setattr(session.get(User, run.owner_id), field, False)
            session.commit()

    video_source["at_start"] = revoke
    work()
    with control_session_factory()() as session:
        assert session.get(Run, identity).status == "canceled"
        assert not list(session.scalars(select(ModelFile))) and not list(session.scalars(select(Artifact)))
        assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
    assert video_source["cancels"] and not video_source["adoptions"]
    assert len(video_source["starts"]) == 1


@pytest.mark.parametrize("stop", [False, True])
def test_expired_worker_reattaches_frozen_video_operation_without_downloading_again(video_source, stop):
    from app.engine import claim_next
    from app.recovery import recover_stale
    from app.runs import request_cancel, transition
    from app.state import RunStatus
    from app.video_setup_job import VideoSetupExecutor

    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(video_source)).json()
        identity = created["run"]["id"]
        with control_session_factory()() as session:
            run = claim_next(session, "expired-video-worker")
            assert run.id == identity
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            contract = VideoSetupExecutor()
            assert contract.before_native(session, run, lambda: False) is False
            run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
            contract.runner().prepare_runtime(contract.payload(run))
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            run.lease_expires_at = utcnow() - timedelta(seconds=2)
            session.add(ResourceLock(resource_key="ram:" + identity, run_id=identity))
            session.commit()
            assert identity in recover_stale(session)
            session.commit()
            run = session.get(Run, identity, populate_existing=True)
            assert run.status == "queued"
            assert (
                session.scalar(select(ResourceLock).where(ResourceLock.run_id == identity)).released_at
                is None
            )
            if stop:
                request_cancel(session, run)
                session.commit()
        downloads = list(video_source["source"]["calls"])
        assert work() == identity
        current = api.get("/api/runs/" + identity).json()
        assert current["status"] == ("canceled" if stop else "succeeded"), current
        assert video_source["source"]["calls"] == downloads
        if stop:
            assert len(video_source["starts"]) == 1 and video_source["cancels"]
            assert not video_source["adoptions"]
        else:
            assert len(video_source["starts"]) == 2
            assert video_source["starts"][0] == video_source["starts"][1]
        with control_session_factory()() as session:
            assert all(
                row.released_at is not None
                for row in session.scalars(select(ResourceLock).where(ResourceLock.run_id == identity))
            )
