"""Real account/API/worker/download path with tiny inputs and a fake native SDK."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from app import runtime_setup_api
from app.api import app
from app.avatar_setup_client import AvatarSetupClient
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import Artifact, ModelFile, ResourceLock, Run, User
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_model_bundles import bundle_source as bundle_source


@pytest.fixture
def avatar_source(bundle_source, monkeypatch):
    entry = bundle_source["entry"]
    recipe = {
        "profile": runtime_setup_api.AVATAR_PROFILE,
        "model_revision": entry.revision,
        "model_license_url": entry.license_url,
        "model_repository": entry.repository,
        "inputs": [],
    }
    import hashlib

    payloads = bundle_source["payloads"]
    payloads.update({"python.bin": b"python runtime", "sdk.bin": b"SDK source", "wheel.bin": b"fixed wheel"})
    payloads.update({f"companion-{i}.json": f"fixed companion {i}".encode() for i in range(11)})
    payloads["source.bin"] = b"pinned pure source"
    kinds = {"python.bin": "python", "sdk.bin": "sdk", "wheel.bin": "wheel", "source.bin": "sdist"}
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
        AvatarSetupClient,
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
        log = json.dumps({"avatar_preparation": {"phase": "installing_dependencies"}}) + "\n"
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
            "profile": runtime_setup_api.AVATAR_PROFILE,
            "environment_prepared": True,
            "avatar_inference_tested_now": False,
        }

    monkeypatch.setattr(AvatarSetupClient, "prepare_runtime", prepare)
    monkeypatch.setattr(AvatarSetupClient, "inspect_runtime_preparation", inspect)
    monkeypatch.setattr(AvatarSetupClient, "cancel_runtime_preparation", cancel)
    monkeypatch.setattr(AvatarSetupClient, "adopt_avatar_environment", adopt)
    state["source"] = bundle_source
    return state


def body(source):
    return {
        "client_request_id": str(uuid4()),
        "profile": runtime_setup_api.AVATAR_PROFILE,
        "manifest_sha256": source["manifest_sha256"],
        "license_accepted": True,
    }


def work():
    with control_session_factory()() as session:
        return tick(session, "avatar-worker")


def test_complete_avatar_install_uses_owned_queue_verified_inputs_and_native_supervisor(avatar_source):
    with TestClient(app) as api:
        request = body(avatar_source)
        catalog = api.get("/api/setup/runtimes", params={"profile": request["profile"]})
        assert catalog.status_code == 200 and catalog.json()["installation_available"]
        created = api.post("/api/setup/runtimes", json=request)
        assert created.status_code == 202, created.text
        value = created.json()
        assert not avatar_source["starts"] and not avatar_source["source"]["calls"]
        assert value["run"]["executor_type"] == "avatar_setup"
        assert value["run"]["requested_resources"]["ram_mib"] == 4096
        assert api.post("/api/setup/runtimes", json=request).json()["id"] == value["id"]
        work()
        completed = api.get("/api/setup/runtimes/preparations/" + value["id"]).json()
        assert completed["run"]["status"] == "succeeded", api.get(
            "/api/runs/" + completed["run"]["id"] + "/events"
        ).json()[-1]["payload"]
        assert completed["progress"]["phase"] == "environment_prepared"
        assert completed["progress"]["avatar_inference_tested"] is False
        assert avatar_source["adoptions"] == [completed["run"]["id"]]
        assert api.get("/api/setup/runtimes/preparations").json() == []
        assert (
            len(api.get("/api/setup/runtimes/preparations", params={"profile": request["profile"]}).json())
            == 1
        )
        with control_session_factory()() as session:
            assert len(list(session.scalars(select(ModelFile)))) == 14
            assert len(list(session.scalars(select(Artifact)))) == 1
            assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
        assert "runtime.avatar.prepared" in api.get("/api/runs/" + completed["run"]["id"] + "/stream").text


def test_corrupt_input_never_starts_or_publishes_a_avatar_environment(avatar_source):
    avatar_source["source"]["corrupt"] = True
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(avatar_source)).json()
        work()
        result = api.get("/api/runs/" + created["run"]["id"]).json()
        assert result["status"] == "failed"
        assert not avatar_source["starts"] and not avatar_source["adoptions"]
        with control_session_factory()() as session:
            assert not list(session.scalars(select(ModelFile))) and not list(
                session.scalars(select(Artifact))
            )
            assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


def test_stop_and_resume_keep_download_bytes_and_original_manifest(avatar_source):
    source = avatar_source["source"]
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(avatar_source)).json()
        original = avatar_source["recipe"]

        def stop(name):
            if name == "weights.safetensors":
                source["hook"] = None
                api.post("/api/setup/runtimes/preparations/" + created["id"] + "/cancel").raise_for_status()

        source["hook"] = stop
        work()
        current = api.get("/api/setup/runtimes/preparations/" + created["id"]).json()
        assert current["run"]["status"] == "canceled" and not avatar_source["starts"]
        avatar_source["recipe"] = {"profile": "unavailable new catalog"}
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


def test_stop_after_native_start_cannot_publish_shared_or_private_receipts(avatar_source):
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(avatar_source)).json()
        avatar_source["at_start"] = lambda _: api.post(
            "/api/setup/runtimes/preparations/" + created["id"] + "/cancel"
        ).raise_for_status()
        work()
        assert api.get("/api/runs/" + created["run"]["id"]).json()["status"] == "canceled"
        assert avatar_source["cancels"] and not avatar_source["adoptions"]
        with control_session_factory()() as session:
            assert not list(session.scalars(select(ModelFile))) and not list(
                session.scalars(select(Artifact))
            )


def test_private_avatar_setup_history_and_receipt_with_shared_model_files(accounts, avatar_source):
    owner, alice, bob = accounts
    assert alice.post("/api/setup/runtimes", json=body(avatar_source)).status_code == 403
    created = owner.post("/api/setup/runtimes", json=body(avatar_source)).json()
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
def test_stale_avatar_setup_cannot_publish_or_release_replacement(
    avatar_source, monkeypatch, boundary, same_worker
):
    from app import runtime_setup_job

    state = {}

    def transfer():
        with control_session_factory()() as session:
            run = session.get(Run, state["id"])
            run.worker_id = run.worker_id if same_worker else "replacement-avatar-worker"
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
        avatar_source["source"]["hook"] = lambda _: transfer()
    elif boundary in {"dispatch", "failure"}:
        avatar_source["at_start"] = dispatched
    else:
        original = runtime_setup_job.lock_task

        def before_publication(session, task):
            session.rollback()
            transfer()
            return original(session, task)

        monkeypatch.setattr(runtime_setup_job, "lock_task", before_publication)
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(avatar_source)).json()
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
        assert not avatar_source["adoptions"]


@pytest.mark.parametrize("field", ["enabled", "is_admin"])
def test_revoked_avatar_setup_authority_only_cancels_owned_native_action(accounts, avatar_source, field):
    owner, _, _ = accounts
    created = owner.post("/api/setup/runtimes", json=body(avatar_source)).json()
    identity = created["run"]["id"]

    def revoke(payload):
        with control_session_factory()() as session:
            run = session.get(Run, identity)
            setattr(session.get(User, run.owner_id), field, False)
            session.commit()

    avatar_source["at_start"] = revoke
    work()
    with control_session_factory()() as session:
        assert session.get(Run, identity).status == "canceled"
        assert not list(session.scalars(select(ModelFile))) and not list(session.scalars(select(Artifact)))
        assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
    assert avatar_source["cancels"] and not avatar_source["adoptions"]
    assert len(avatar_source["starts"]) == 1


@pytest.mark.parametrize("stop", [False, True])
def test_expired_worker_reattaches_frozen_avatar_operation_without_downloading_again(avatar_source, stop):
    from app.avatar_setup_job import AvatarSetupExecutor
    from app.engine import claim_next
    from app.recovery import recover_stale
    from app.runs import request_cancel, transition
    from app.state import RunStatus

    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(avatar_source)).json()
        identity = created["run"]["id"]
        with control_session_factory()() as session:
            run = claim_next(session, "expired-avatar-worker")
            assert run.id == identity
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            contract = AvatarSetupExecutor()
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
        downloads = list(avatar_source["source"]["calls"])
        assert work() == identity
        current = api.get("/api/runs/" + identity).json()
        assert current["status"] == ("canceled" if stop else "succeeded"), current
        assert avatar_source["source"]["calls"] == downloads
        if stop:
            assert len(avatar_source["starts"]) == 1 and avatar_source["cancels"]
            assert not avatar_source["adoptions"]
        else:
            assert len(avatar_source["starts"]) == 2
            assert avatar_source["starts"][0] == avatar_source["starts"][1]
        with control_session_factory()() as session:
            assert all(
                row.released_at is not None
                for row in session.scalars(select(ResourceLock).where(ResourceLock.run_id == identity))
            )
