"""Image setup uses the real owned API/worker/file primitive and a fake OCI bridge."""

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.db import control_session_factory, utcnow
from app.engine import claim_next, tick
from app.image_setup_client import ImageSetupClient
from app.image_setup_job import ImageSetupExecutor
from app.model_download_files import FileSpec
from app.models import Artifact, ModelFile, ResourceLock, Run, User
from app.recovery import recover_stale
from app.runs import request_cancel, transition
from app.runtime_setup_api import IMAGE_PROFILE, fingerprint
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_model_bundles import bundle_source as bundle_source


@pytest.fixture
def image_source(bundle_source, monkeypatch):
    source = bundle_source
    source["payloads"]["vision.gguf"] = b"tiny vision fixture"
    source["payloads"]["upscaler.pth"] = b"tiny upscaler fixture"
    inputs = []
    for role, (filename, data) in zip(
        ["diffusion", "text_encoder", "vision_projector", "vae", "upscaler"],
        source["payloads"].items(),
        strict=True,
    ):
        spec = FileSpec(
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            urls=("https://models.example.com/pinned/" + filename,),
        )
        inputs.append(
            dict(
                kind="model",
                role=role,
                filename=filename,
                sha256=spec.sha256,
                size_bytes=spec.size_bytes,
                url=spec.urls[0],
                repository="example/fixture",
                revision="a" * 40,
            )
        )
    frozen = dict(
        profile=IMAGE_PROFILE,
        name="Tiny image fixture",
        inputs=inputs,
        model_manifest_sha256="a" * 64,
        license_url="https://models.example.com/LICENSE",
        image_reference="ghcr.io/example/image@sha256:" + "b" * 64,
        download_bytes=2048,
    )
    state = dict(
        recipe=frozen,
        manifest_sha256=fingerprint(frozen),
        starts=[],
        cancels=[],
        source=source,
        at_start=None,
        bad_image=False,
    )
    monkeypatch.setattr(
        ImageSetupClient,
        "runtime_setup_catalog",
        lambda _: dict(
            recipe=state["recipe"], manifest_sha256=state["manifest_sha256"], installation_available=True
        ),
    )

    def start(_, payload):
        state["starts"].append(payload)
        if state["at_start"]:
            state["at_start"](payload)
        return dict(
            run_id=payload["run_id"],
            manifest_sha256=payload["manifest_sha256"],
            status="running",
            alive=True,
            requires_inspection=False,
        )

    def inspect(_, identity, *, stdout_offset=0, stderr_offset=0):
        log = "".join(
            json.dumps(v) + "\n"
            for v in [
                {"type": "runtime.prepare.started"},
                {"type": "runtime.prepare.progress", "received_bytes": 1024, "stage": "downloading"},
                {"type": "runtime.prepare.verifying"},
            ]
        )
        return dict(
            run_id=identity,
            manifest_sha256=state["starts"][-1]["manifest_sha256"],
            status="succeeded",
            alive=False,
            requires_inspection=False,
            image=dict(
                id="sha256:" + "c" * 64,
                platform="linux/amd64",
                reference="different source" if state["bad_image"] else frozen["image_reference"],
            ),
            process=dict(
                pid=123,
                process_group_id=123,
                stdout_log=f"runs/{identity}/stdout.log",
                stderr_log=f"runs/{identity}/stderr.log",
                stdout=log if stdout_offset == 0 else "",
                stderr="",
                stdout_offset=len(log),
                stderr_offset=0,
                stdout_more=False,
                stderr_more=False,
            ),
        )

    def cancel(_, identity, payload):
        state["cancels"].append(identity)
        return dict(
            run_id=identity,
            manifest_sha256=None,
            status="canceled",
            alive=False,
            requires_inspection=False,
            process=None,
        )

    monkeypatch.setattr(ImageSetupClient, "prepare_runtime", start)
    monkeypatch.setattr(ImageSetupClient, "inspect_runtime_preparation", inspect)
    monkeypatch.setattr(ImageSetupClient, "cancel_runtime_preparation", cancel)
    return state


def body(state):
    return dict(
        client_request_id=str(uuid4()),
        profile=IMAGE_PROFILE,
        manifest_sha256=state["manifest_sha256"],
        license_accepted=True,
    )


def work():
    with control_session_factory()() as db:
        return tick(db, "image-setup-worker")


def test_queued_complete_image_setup_registers_shared_image_files_and_one_private_receipt(image_source):
    with TestClient(app) as api:
        payload = body(image_source)
        created = api.post("/api/setup/runtimes", json=payload)
        assert created.status_code == 202, created.text
        value = created.json()
        assert value["run"]["executor_type"] == "image_setup" and not image_source["starts"]
        assert not image_source["source"]["calls"]
        assert api.post("/api/setup/runtimes", json=payload).json()["id"] == value["id"]
        assert work() == value["run"]["id"]
        final = api.get("/api/setup/runtimes/preparations/" + value["id"]).json()
        assert final["run"]["status"] == "succeeded", final["run"]["error_message"]
        assert final["progress"]["phase"] == "image_environment_prepared"
        assert final["progress"]["image_inference_tested"] is False
        assert api.get("/api/setup/runtimes/preparations").json() == []
        assert len(api.get("/api/setup/runtimes/preparations", params={"profile": IMAGE_PROFILE}).json()) == 1
        with control_session_factory()() as db:
            models = list(db.scalars(select(ModelFile)))
            assert len(models) == 5 and all(v.category == "image" for v in models)
            assert all(v.relative_path.startswith("models/store/") and v.host_path is None for v in models)
            assert len(list(db.scalars(select(Artifact)))) == 1
            assert not list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
        assert "runtime.image.prepared" in api.get("/api/runs/" + value["run"]["id"] + "/stream").text


@pytest.mark.parametrize("failure", ["corrupt_file", "wrong_runtime"])
def test_bad_model_or_runtime_never_publishes_any_image_setup_success(image_source, failure):
    if failure == "corrupt_file":
        image_source["source"]["corrupt"] = True
    else:
        image_source["bad_image"] = True
    with TestClient(app) as api:
        value = api.post("/api/setup/runtimes", json=body(image_source)).json()
        work()
        final = api.get("/api/runs/" + value["run"]["id"]).json()
        assert final["status"] == "failed", final
        if failure == "corrupt_file":
            assert not image_source["starts"]
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))
            assert not list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


def test_stop_during_files_and_resume_preserve_original_recipe_and_verified_cache(image_source):
    with TestClient(app) as api:
        value = api.post("/api/setup/runtimes", json=body(image_source)).json()

        def stop(name):
            if name == "weights.safetensors":
                image_source["source"]["hook"] = None
                api.post("/api/setup/runtimes/preparations/" + value["id"] + "/cancel").raise_for_status()

        image_source["source"]["hook"] = stop
        work()
        final = api.get("/api/runs/" + value["run"]["id"]).json()
        assert final["status"] == "canceled" and not image_source["starts"]
        image_source["recipe"] = {"profile": "not-the-original"}
        reply = api.post(
            "/api/setup/runtimes/preparations/" + value["id"] + "/resume",
            json=dict(client_request_id=str(uuid4()), expected_run_id=final["id"]),
        )
        assert reply.status_code == 202, reply.text
        work()
        assert api.get("/api/runs/" + reply.json()["run"]["id"]).json()["status"] == "succeeded"
        assert sum(name == "encoder.pt" for name, _ in image_source["source"]["calls"]) == 1


def test_history_and_receipt_are_private_while_model_files_are_shared(accounts, image_source):
    owner, alice, bob = accounts
    assert alice.post("/api/setup/runtimes", json=body(image_source)).status_code == 403
    value = owner.post("/api/setup/runtimes", json=body(image_source)).json()
    assert bob.get("/api/setup/runtimes/preparations/" + value["id"]).status_code == 404
    work()
    assert owner.get("/api/runs/" + value["run"]["id"]).json()["status"] == "succeeded"
    with control_session_factory()() as db:
        artifact_id = db.scalar(select(Artifact.id))
        model_ids = list(db.scalars(select(ModelFile.id)))
    assert bob.get(f"/api/artifacts/{artifact_id}/file").status_code == 404
    assert owner.get(f"/api/artifacts/{artifact_id}/file").status_code == 200
    assert all(bob.get(f"/api/models/{identity}").status_code == 200 for identity in model_ids)


@pytest.mark.parametrize("stop", [False, True])
def test_stale_worker_reuses_native_identity_and_confirmed_stop_before_releasing_locks(image_source, stop):
    with TestClient(app) as api:
        value = api.post("/api/setup/runtimes", json=body(image_source)).json()
        identity = value["run"]["id"]
        with control_session_factory()() as db:
            run = claim_next(db, "old-image-worker")
            assert run.id == identity
            transition(db, run, RunStatus.PREPARING, event_type="executor.preparing")
            contract = ImageSetupExecutor()
            assert contract.before_native(db, run, lambda: False) is False
            run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
            contract.runner().prepare_runtime(contract.payload(run))
            transition(db, run, RunStatus.RUNNING, event_type="executor.started")
            run.lease_expires_at = utcnow() - timedelta(seconds=2)
            db.add(ResourceLock(resource_key="ram:" + identity, run_id=identity))
            db.commit()
            assert identity in recover_stale(db)
            db.commit()
            run = db.get(Run, identity, populate_existing=True)
            if stop:
                request_cancel(db, run)
                db.commit()
        downloads = list(image_source["source"]["calls"])
        assert work() == identity
        assert api.get("/api/runs/" + identity).json()["status"] == ("canceled" if stop else "succeeded")
        assert image_source["source"]["calls"] == downloads
        assert len(image_source["starts"]) == (1 if stop else 2)
        if not stop:
            assert image_source["starts"][0] == image_source["starts"][1]
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


@pytest.mark.parametrize("field", ["enabled", "is_admin"])
def test_revoked_administrator_cancels_only_its_existing_image_setup(accounts, image_source, field):
    owner, _, _ = accounts
    value = owner.post("/api/setup/runtimes", json=body(image_source)).json()
    identity = value["run"]["id"]

    def revoke(payload):
        with control_session_factory()() as db:
            run = db.get(Run, identity)
            setattr(db.get(User, run.owner_id), field, False)
            db.commit()

    image_source["at_start"] = revoke
    work()
    with control_session_factory()() as db:
        assert db.get(Run, identity).status == "canceled"
        assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))
    assert image_source["cancels"] and len(image_source["starts"]) == 1


@pytest.mark.parametrize("same_worker", [False, True])
@pytest.mark.parametrize("boundary", ["download", "dispatch", "publication", "failure"])
def test_stale_image_setup_cannot_publish_or_release_replacement_locks(
    image_source, monkeypatch, same_worker, boundary
):
    from app import runtime_setup_job

    state = {}

    def transfer():
        with control_session_factory()() as db:
            run = db.get(Run, state["id"])
            run.worker_id = run.worker_id if same_worker else "replacement-image-worker"
            run.claimed_at = utcnow() + timedelta(seconds=1)
            run.lease_expires_at = utcnow() + timedelta(minutes=5)
            state.update(worker=run.worker_id, claim=run.claimed_at)
            for lock in db.scalars(select(ResourceLock).where(ResourceLock.run_id == run.id)):
                lock.released_at = utcnow()
            db.flush()
            lock = ResourceLock(resource_key="ram:" + run.id, run_id=run.id)
            db.add(lock)
            db.flush()
            state["lock"] = lock.id
            db.commit()

    def dispatched(_):
        transfer()
        if boundary == "failure":
            raise ValueError("Synthetic stale image response failure")

    if boundary == "download":
        image_source["source"]["hook"] = lambda _: transfer()
    elif boundary in {"dispatch", "failure"}:
        image_source["at_start"] = dispatched
    else:
        original = runtime_setup_job.lock_task

        def before_publication(db, task):
            db.rollback()
            transfer()
            return original(db, task)

        monkeypatch.setattr(runtime_setup_job, "lock_task", before_publication)
    with TestClient(app) as api:
        value = api.post("/api/setup/runtimes", json=body(image_source)).json()
        state["id"] = value["run"]["id"]
        work()
        with control_session_factory()() as db:
            run = db.get(Run, state["id"])
            assert run.worker_id == state["worker"] and run.claimed_at == state["claim"]
            assert run.status not in {"succeeded", "failed", "canceled"}
            assert db.get(ResourceLock, state["lock"]).released_at is None
            assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))


def test_stop_after_native_start_cannot_publish_model_or_private_receipt(image_source):
    with TestClient(app) as api:
        value = api.post("/api/setup/runtimes", json=body(image_source)).json()
        image_source["at_start"] = lambda _: api.post(
            "/api/setup/runtimes/preparations/" + value["id"] + "/cancel"
        ).raise_for_status()
        work()
        assert api.get("/api/runs/" + value["run"]["id"]).json()["status"] == "canceled"
        assert image_source["cancels"]
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))
