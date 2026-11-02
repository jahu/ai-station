"""API/worker/download/receipt path with a tiny SDK and a fake native Runner."""

import hashlib
from uuid import uuid4

import pytest
from app import runtime_setup_api
from app.api import app
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import Artifact, ModelFile, ResourceLock, Run, User
from app.native_llama_setup_client import NativeLlamaSetupClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_model_bundles import bundle_source as bundle_source


@pytest.fixture
def native_source(bundle_source, monkeypatch):
    name = "native-sdk.tgz"
    raw = b"controlled synthetic native SDK archive"
    bundle_source["payloads"][name] = raw
    profile = "llamacpp-native-darwin-arm64-b12032-v2"
    recipe = {
        "profile": profile,
        "platform": "darwin/arm64",
        "release": "b12032",
        "inputs": [
            {
                "kind": "native_engine",
                "filename": name,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "url": "https://models.example.com/pinned/" + name,
            }
        ],
    }
    state = {
        "recipe": recipe,
        "manifest_sha256": runtime_setup_api.fingerprint(recipe),
        "starts": [],
        "adoptions": [],
        "cancels": [],
        "source": bundle_source,
        "at_start": None,
    }
    monkeypatch.setattr(
        NativeLlamaSetupClient,
        "runtime_setup_catalog",
        lambda _, profile: {
            "recipe": recipe,
            "manifest_sha256": state["manifest_sha256"],
            "installation_available": True,
        },
    )

    def start(_, body):
        state["starts"].append(body)
        if state["at_start"]:
            state["at_start"](body)
        return {
            "run_id": body["run_id"],
            "manifest_sha256": body["manifest_sha256"],
            "status": "running",
            "alive": True,
            "requires_inspection": False,
        }

    def inspect(_, identity, **kwargs):
        return {
            "run_id": identity,
            "manifest_sha256": state["manifest_sha256"],
            "status": "succeeded",
            "alive": False,
            "requires_inspection": False,
            "environment_prepared": True,
        }

    def adopt(_, identity, body):
        state["adoptions"].append(identity)
        observation = {
            "profile": profile,
            "operation_id": identity,
            "manifest_sha256": state["manifest_sha256"],
        }
        return {
            **observation,
            "environment_id": runtime_setup_api.fingerprint(observation),
            "environment_prepared": True,
            "sdk_prepared": True,
            "inference_tested_now": False,
        }

    def cancel(_, identity, body):
        state["cancels"].append(identity)
        return {
            "run_id": identity,
            "manifest_sha256": None,
            "status": "canceled",
            "alive": False,
            "requires_inspection": False,
            "process": None,
        }

    monkeypatch.setattr(NativeLlamaSetupClient, "prepare_runtime", start)
    monkeypatch.setattr(NativeLlamaSetupClient, "inspect_runtime_preparation", inspect)
    monkeypatch.setattr(NativeLlamaSetupClient, "adopt_native_llama_environment", adopt)
    monkeypatch.setattr(NativeLlamaSetupClient, "cancel_runtime_preparation", cancel)
    return state


def body(state):
    return {
        "client_request_id": str(uuid4()),
        "profile": state["recipe"]["profile"],
        "manifest_sha256": state["manifest_sha256"],
        "license_accepted": True,
    }


def work():
    with control_session_factory()() as session:
        assert tick(session, worker_id="native-sdk-unit")


def test_native_sdk_queues_downloads_verifies_and_publishes_a_private_receipt(native_source):
    with TestClient(app) as api:
        request = body(native_source)
        created = api.post("/api/setup/runtimes", json=request)
        assert created.status_code == 202, created.text
        value = created.json()
        assert value["run"]["executor_type"] == "native_llama_setup"
        assert value["run"]["requested_resources"]["ram_mib"] == 1024
        assert not native_source["starts"] and not native_source["source"]["calls"]
        assert api.post("/api/setup/runtimes", json=request).json()["id"] == value["id"]
        work()
        result = api.get("/api/setup/runtimes/preparations/" + value["id"]).json()
        assert result["run"]["status"] == "succeeded", api.get(
            "/api/runs/" + value["run"]["id"] + "/events"
        ).json()[-1]
        assert result["progress"]["phase"] == "environment_prepared"
        assert result["progress"]["model_inference_tested"] is False
        assert native_source["adoptions"] == [value["run"]["id"]]
        with control_session_factory()() as session:
            assert not list(session.scalars(select(ModelFile)))
            assert len(list(session.scalars(select(Artifact)))) == 1
            assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
        assert "runtime.native_llama.prepared" in api.get("/api/runs/" + value["run"]["id"] + "/stream").text


def test_corrupt_sdk_archive_never_starts_or_activates_native_environment(native_source):
    native_source["source"]["payloads"]["native-sdk.tgz"] = (
        b"x" * native_source["recipe"]["inputs"][0]["size_bytes"]
    )
    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(native_source)).json()
        work()
        assert api.get("/api/runs/" + created["run"]["id"]).json()["status"] == "failed"
        assert not native_source["starts"] and not native_source["adoptions"]
        with control_session_factory()() as session:
            assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


def test_native_sdk_requires_administrator_and_preserves_private_history(
    native_source, private_app, accounts
):
    owner, alice, bob = accounts
    assert alice.post("/api/setup/runtimes", json=body(native_source)).status_code == 403
    created = owner.post("/api/setup/runtimes", json=body(native_source)).json()
    assert bob.get("/api/setup/runtimes/preparations/" + created["id"]).status_code == 404
    work()
    with control_session_factory()() as session:
        artifact = session.scalar(select(Artifact))
        artifact_id = artifact.id
    assert bob.get("/api/artifacts/" + artifact_id + "/file").status_code == 404
    assert owner.get("/api/artifacts/" + artifact_id + "/file").status_code == 200


@pytest.mark.parametrize("field", ["enabled", "is_admin"])
def test_revoked_operator_cancels_sdk_setup_and_never_activates(native_source, accounts, field):
    owner, _, _ = accounts
    created = owner.post("/api/setup/runtimes", json=body(native_source)).json()
    identity = created["run"]["id"]

    def revoke(payload):
        with control_session_factory()() as session:
            run = session.get(Run, identity)
            setattr(session.get(User, run.owner_id), field, False)
            session.commit()

    native_source["at_start"] = revoke
    work()
    with control_session_factory()() as session:
        assert session.get(Run, identity).status == "canceled"
        assert not list(session.scalars(select(Artifact)))
        assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
    assert native_source["cancels"] and not native_source["adoptions"]


@pytest.mark.parametrize("stop", [False, True])
def test_expired_worker_reattaches_same_sdk_run_without_redownload(native_source, stop):
    from datetime import timedelta

    from app.engine import claim_next
    from app.native_llama_setup_job import NativeLlamaSetupExecutor
    from app.recovery import recover_stale
    from app.runs import request_cancel, transition
    from app.state import RunStatus

    with TestClient(app) as api:
        created = api.post("/api/setup/runtimes", json=body(native_source)).json()
        identity = created["run"]["id"]
        with control_session_factory()() as session:
            run = claim_next(session, "expired-native-worker")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            contract = NativeLlamaSetupExecutor()
            assert contract.before_native(session, run, lambda: False) is False
            run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
            contract.runner().prepare_runtime(contract.payload(run))
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            run.lease_expires_at = utcnow() - timedelta(seconds=2)
            session.add(ResourceLock(resource_key="ram:" + identity, run_id=identity))
            session.commit()
            assert identity in recover_stale(session)
            session.commit()
            if stop:
                request_cancel(session, session.get(Run, identity, populate_existing=True))
                session.commit()
        downloads = list(native_source["source"]["calls"])
        work()
        assert api.get("/api/runs/" + identity).json()["status"] == ("canceled" if stop else "succeeded")
        assert native_source["source"]["calls"] == downloads
