from uuid import uuid4

import pytest
from app.db import control_session_factory
from app.live_executor import LiveExecutor
from app.live_portrait_setup_job import PortraitSetupExecutor
from app.live_setup_client import PortraitSetupClient
from app.models import Run
from app.runner_client import RunnerClient
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload

PROFILE = "live-portrait-linux-x86-64-python312-v1"


@pytest.fixture
def ready_portrait(monkeypatch):
    calls = []

    def request(self, method, path, json=None):
        calls.append((method, path, json))
        assert method == "GET" and path in ("/v1/live/capabilities", "/v1/live/capabilities?mode=portrait"), (
            "HTTP enqueue dispatched inference"
        )
        return {
            "available": True,
            "eligible_gpu_indices": [3, 7],
            "managed_runtime": {
                "profile": PROFILE if "?mode=" in path else "live-identity-linux-x86-64-python312-v1",
                "manifest_sha256": "a" * 64,
                "environment_id": "b" * 64,
            },
        }

    monkeypatch.setattr(RunnerClient, "request", request)
    return calls


def test_portrait_selection_is_frozen_idempotent_private_and_survives_dispatch(accounts, ready_portrait):
    _, alice, bob = accounts
    source, _ = upload(alice, "green")
    token = str(uuid4())
    body = {"client_request_id": token, "mode": "portrait", "image_artifact_id": source}
    result = alice.post("/api/live/sessions", json=body)
    assert result.status_code == 202, result.text
    run = result.json()["run"]
    assert run["parameters"]["mode"] == "portrait"
    assert run["parameters"]["managed_runtime"]["profile"] == PROFILE
    assert alice.post("/api/live/sessions", json=body).json()["run"]["id"] == run["id"]
    assert alice.post("/api/live/sessions", json={**body, "mode": "face_swap"}).status_code == 409
    assert bob.get("/api/live/sessions/" + run["id"]).status_code == 404
    assert any(path.endswith("?mode=portrait") for _, path, _ in ready_portrait)

    class Runner:
        def request(self, *args):
            return args

    with control_session_factory()() as s:
        item = s.get(Run, run["id"])
        item.allocated_resources = {"gpus": ["3"]}
        _, _, native = LiveExecutor()._start(Runner(), item, None, None)
        assert native["mode"] == "portrait" and native["managed_runtime"]["profile"] == PROFILE


def test_portrait_cannot_be_started_voice_only_or_from_another_accounts_image(accounts, ready_portrait):
    _, alice, bob = accounts
    source, _ = upload(alice, "green")
    for changes in ({"voice_artifact_id": str(uuid4())}, {"mode": "unknown"}):
        response = alice.post(
            "/api/live/sessions", json={"client_request_id": str(uuid4()), "mode": "portrait", **changes}
        )
        assert response.status_code == 422
    assert (
        bob.post(
            "/api/live/sessions",
            json={"client_request_id": str(uuid4()), "mode": "portrait", "image_artifact_id": source},
        ).status_code
        == 422
    )
    assert not bob.get("/api/live/sessions").json()


def test_portrait_preparation_uses_its_closed_native_namespace():
    client = PortraitSetupClient()
    client.request = lambda *args: args
    assert client.runtime_setup_catalog() == ("GET", "/v1/setup/live-portrait")
    assert client.prepare_runtime({"x": 1}) == ("POST", "/v1/setup/live-portrait/prepare", {"x": 1})
    assert client.cancel_runtime_preparation("id", {}) == ("POST", "/v1/setup/live-portrait/id/cancel", {})
    executor = PortraitSetupExecutor()
    assert executor.profile == PROFILE and executor.name == "live_portrait_setup"


def test_portrait_setup_is_admin_only_queued_and_validates_the_real_recipe(accounts, monkeypatch):
    import json
    from pathlib import Path

    from app.model_setup import fingerprint

    recipe = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "host-runner/ai_station_runner/recipes"
            / (PROFILE + ".json")
        ).read_text()
    )
    catalog = {"recipe": recipe, "manifest_sha256": fingerprint(recipe), "installation_available": True}
    monkeypatch.setattr(PortraitSetupClient, "runtime_setup_catalog", lambda _: catalog)
    owner, alice, _ = accounts
    body = {
        "client_request_id": str(uuid4()),
        "profile": PROFILE,
        "manifest_sha256": catalog["manifest_sha256"],
        "license_accepted": True,
    }
    assert alice.post("/api/setup/runtimes", json=body).status_code == 403
    result = owner.post("/api/setup/runtimes", json=body)
    assert result.status_code == 202, result.text
    run = result.json()["run"]
    assert run["executor_type"] == "live_portrait_setup" and run["status"] == "queued"
    assert alice.get("/api/runs/" + run["id"]).status_code == 404
    with control_session_factory()() as s:
        item = s.get(Run, run["id"])
        contract = PortraitSetupExecutor()
        contract.validate(item)
        assert len(contract.bundle(recipe).files) == 5
        item.metadata_json = {"live_portrait_native_deadline_at": item.parameters["execution_deadline_at"]}
        assert contract.payload(item)["profile"] == PROFILE
        item.parameters = {**item.parameters, "manifest_sha256": "0" * 64}
        with pytest.raises(ValueError):
            contract.validate(item)
