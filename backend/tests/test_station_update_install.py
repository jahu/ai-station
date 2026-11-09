from datetime import timedelta
from uuid import uuid4

import pytest
from ai_station_runner.station_release_metadata import admit_release
from app import station_release_source as source
from app import station_update_install as module
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import Run, Setting
from app.recovery import recover_stale
from app.runs import claim_next, request_cancel
from app.station_update_gate import KEY, take
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_station_update_gate import job
from test_station_updates import release

TARGET = {
    "version": "0.5.0",
    "bundle_id": "d" * 64,
    "image_id": "sha256:" + "e" * 64,
    "source_epoch": 1794210001,
}


@pytest.fixture
def offer(accounts, monkeypatch):
    monkeypatch.setattr(module, "__version__", "0.4.0")  # Fixed synthetic old-client scenario.
    snapshot = admit_release(release())

    async def metadata(check, **kwargs):
        check()
        return snapshot

    monkeypatch.setattr(source, "release_metadata", metadata)
    owner = accounts[0]
    identity = owner.post("/api/maintenance/updates/checks", json={}).json()["id"]
    with control_session_factory()() as session:
        tick(session, "release-check")
        assert session.get(Run, identity).status == "succeeded"
    return {
        "check_run_id": identity,
        "fingerprint": snapshot["fingerprint"],
        "client_request_id": str(uuid4()),
    }


class Native:
    def __init__(self, phase="failed", hook=lambda value: None):
        self.phase, self.hook, self.calls = phase, hook, []

    def station_update_capabilities(self):
        return {"installed": True, "apply_available": True, "version": "0.4.0", "platform": "linux-amd64"}

    def station_update(self, value):
        self.calls.append(value)
        self.hook(value)
        return {
            "run_id": value["run_id"],
            "request": self.parameters,
            "phase": "canceled" if value["action"] == "cancel" else self.phase,
            "target": TARGET,
        }


def installed(accounts, offer, monkeypatch, native=None):
    native = native or Native()
    monkeypatch.setattr(module, "RunnerClient", lambda **kwargs: native)
    response = accounts[0].post("/api/maintenance/updates/install", json=offer)
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    with control_session_factory()() as session:
        native.parameters = dict(session.get(Run, run_id).parameters)
    return run_id, native


def test_install_is_owned_frozen_idempotent_and_never_downloads_in_http(accounts, offer, monkeypatch):
    identity, native = installed(accounts, offer, monkeypatch)
    assert not native.calls
    assert accounts[0].post("/api/maintenance/updates/install", json=offer).json()["id"] == identity
    assert accounts[1].post("/api/maintenance/updates/install", json=offer).status_code == 403
    assert accounts[1].get(f"/api/runs/{identity}").status_code == 404
    assert (
        accounts[0]
        .post("/api/maintenance/updates/install", json={**offer, "url": "https://other.example"})
        .status_code
        == 422
    )
    with control_session_factory()() as session:
        row = session.get(Run, identity)
        assert row.parameters["release_id"] == 123
        assert row.parameters["fingerprint"] == offer["fingerprint"]
        assert row.retry_class == "inspect"
        tick(session, "installer")
        session.expire_all()
        assert session.get(Run, identity).status == "failed"
    assert [call["action"] for call in native.calls] == ["prepare"]


def test_unqualified_native_installation_is_unavailable(accounts, offer, monkeypatch):
    class Unavailable(Native):
        def station_update_capabilities(self):
            return {"installed": True, "apply_available": False, "version": "0.4.0"}

    native = Unavailable()
    monkeypatch.setattr(module, "RunnerClient", lambda **kwargs: native)
    assert accounts[0].post("/api/maintenance/updates/install", json=offer).status_code == 409
    assert not native.calls


def test_cancel_during_preparation_never_acquires_gate_or_applies(accounts, offer, monkeypatch):
    def cancel(value):
        if value["action"] == "prepare":
            with control_session_factory()() as other:
                request_cancel(other, other.get(Run, value["run_id"]))
                other.commit()

    identity, native = installed(accounts, offer, monkeypatch, Native("ready", cancel))
    with control_session_factory()() as session:
        tick(session, "installer")
        session.expire_all()
        assert session.get(Run, identity).status == "canceled"
        assert session.get(Setting, KEY) is None
    assert [call["action"] for call in native.calls] == ["prepare", "cancel"]


def test_idle_gate_precedes_apply_and_is_kept_on_uncertain_activation(accounts, offer, monkeypatch):
    class Preparing(Native):
        def station_update(self, value):
            self.calls.append(value)
            if value["action"] == "apply":
                with control_session_factory()() as other:
                    assert other.get(Setting, KEY).value["run_id"] == value["run_id"]
                    assert claim_next(other, "other-worker") is None
                phase = "inspection_required"
            else:
                phase = "ready"
            return {"run_id": value["run_id"], "request": self.parameters, "phase": phase, "target": TARGET}

    identity, native = installed(accounts, offer, monkeypatch, Preparing())
    with control_session_factory()() as session:
        waiting = job(session)
        tick(session, "installer")
        session.expire_all()
        assert session.get(Run, identity).status == "interrupted"
        assert session.get(Run, waiting).status == "queued"
        assert session.get(Setting, KEY).value["run_id"] == identity
    assert [call["action"] for call in native.calls] == ["prepare", "apply"]


def test_restart_recovers_original_native_proof_and_clears_gate_without_install_replay(
    accounts, offer, monkeypatch
):
    identity, native = installed(accounts, offer, monkeypatch)
    with control_session_factory()() as session:
        run = claim_next(session, "old-installer")
        assert run.id == identity
        run.status = "running"
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        session.commit()
        claim = run.worker_id, run.claimed_at
    take(identity, claim)
    with control_session_factory()() as session:
        row = session.get(Run, identity)
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    calls = []

    class Complete:
        def station_update(self, value):
            calls.append(value["action"])
            return {
                "run_id": identity,
                "request": native.parameters,
                "phase": "succeeded",
                "target": TARGET,
            }

    monkeypatch.setattr(module, "__version__", "0.5.0")  # Synthetic post-upgrade app.
    with control_session_factory()() as session:
        assert recover_stale(session, Complete()) == [identity]
        assert session.get(Run, identity).status == "succeeded"
        assert session.get(Setting, KEY) is None
    assert calls == ["inspect"] and not native.calls


def test_unavailable_native_inspection_is_bounded_and_never_redispatches(accounts, offer, monkeypatch):
    from app.runner_client import RunnerUnavailable

    identity, native = installed(accounts, offer, monkeypatch)
    calls = []

    class Offline:
        def station_update(self, value):
            calls.append(value["action"])
            raise RunnerUnavailable("Synthetic native restart")

    with control_session_factory()() as session:
        run = claim_next(session, "old-installer")
        run.status = "running"
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
        recover_stale(session, Offline())
        recover_stale(session, Offline())
        assert session.get(Run, identity).status == "running"
    assert calls == ["inspect"] and not native.calls
