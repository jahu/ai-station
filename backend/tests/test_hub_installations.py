"""New source → plan → existing downloader → native GGUF verification/catalog."""

from uuid import uuid4

import pytest
from app import hub_candidates, model_hub
from app.api import app
from app.db import control_session_factory
from app.engine import tick
from app.hub_candidates import HubCandidate
from app.models import ModelDefinition, ModelFile
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_model_setup import setup_bridge  # noqa: F401


def work():
    with control_session_factory()() as db:
        tick(db, "hub-install-test")


@pytest.fixture
def new_model(setup_bridge, monkeypatch):  # noqa: F811
    original = setup_bridge["entry"]
    values = original.model_dump(mode="json")
    values.update(
        origin="hub",
        id="hub-" + original.file.sha256[:24],
        name="New community model",
        repository="publisher/new-model",
        revision="a" * 40,
        configuration_repository="publisher/base",
        configuration_revision="c" * 40,
        configuration_sha256="d" * 64,
        config_url="https://huggingface.co/publisher/base/resolve/" + "c" * 40 + "/config.json",
    )
    values["file"] = {
        **values["file"],
        "urls": ["https://huggingface.co/publisher/new-model/resolve/" + "a" * 40 + "/" + values["filename"]],
    }
    values["source_url"] = "https://huggingface.co/publisher/new-model/tree/" + "a" * 40
    values["license_url"] = "https://huggingface.co/publisher/new-model/blob/" + "a" * 40 + "/README.md"
    entry = HubCandidate.model_validate(values)
    observed = {
        "repository": entry.repository,
        "revision": entry.revision,
        "source_url": entry.source_url,
        "license": entry.license,
        "license_url": entry.license_url,
        "files": [
            {
                "filename": entry.filename,
                "size_bytes": entry.file.size_bytes,
                "sha256": entry.file.sha256,
                "identity_available": True,
                "format": "gguf",
            }
        ],
    }

    async def inspect(*args):
        return observed

    state = {"entry": entry, **setup_bridge}
    # Keep the hub object under a distinct key; it is absent from curated IDs.
    state["hub_entry"] = entry

    async def resolve(*args):
        return state["hub_entry"]

    monkeypatch.setattr(model_hub, "inspect_source", inspect)
    monkeypatch.setattr(hub_candidates, "resolve_candidate", resolve)
    return state


def reviewed_plan(api, new_model):
    created = api.post(
        "/api/model-hub/inspections",
        json={"client_request_id": str(uuid4()), "source": "publisher/new-model"},
    )
    assert created.status_code == 202, created.text
    work()
    source = api.get("/api/runs/" + created.json()["id"]).json()
    report = source["metadata"]["source_inspection"]
    request = {
        "client_request_id": str(uuid4()),
        "inspection_run_id": source["id"],
        "observation_sha256": report["observation_sha256"],
        "filename": new_model["hub_entry"].filename,
    }
    planned = api.post("/api/model-hub/plans", json=request)
    assert planned.status_code == 202, planned.text
    assert api.post("/api/model-hub/plans", json=request).json()["id"] == planned.json()["id"]
    work()
    result = api.get("/api/runs/" + planned.json()["id"]).json()
    assert result["status"] == "succeeded", result
    return result


def install_request(plan, **updates):
    return {
        "client_request_id": str(uuid4()),
        "plan_run_id": plan["id"],
        "manifest_sha256": plan["metadata"]["source_inspection"]["manifest_sha256"],
        "license_accepted": True,
        **updates,
    }


def test_new_model_download_uses_native_inspection_and_appears_in_chat_catalog(new_model):
    with TestClient(app) as api:
        plan = reviewed_plan(api, new_model)
        assert not new_model["calls"]
        request = install_request(plan)
        accepted = api.post("/api/model-hub/downloads", json=request)
        assert accepted.status_code == 202, accepted.text
        assert (
            api.post("/api/model-hub/downloads", json=request).json()["run"]["id"]
            == accepted.json()["run"]["id"]
        )
        work()
        saved = api.get("/api/setup/downloads/" + accepted.json()["id"]).json()
        assert saved["run"]["status"] == "succeeded", saved
        assert len(new_model["calls"]) == 1
        assert saved["model_key"].startswith("llamacpp:")
        catalog = api.get("/api/chat/model-catalog").json()
        assert any(m["model_ref"] == saved["model_key"] for m in catalog["models"])
    with control_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelFile)) == 1
        assert db.scalar(select(func.count()).select_from(ModelDefinition)) == 1


def test_declining_license_or_changing_plan_identity_never_downloads(new_model):
    with TestClient(app) as api:
        plan = reviewed_plan(api, new_model)
        assert (
            api.post(
                "/api/model-hub/downloads", json=install_request(plan, license_accepted=False)
            ).status_code
            == 422
        )
        assert (
            api.post(
                "/api/model-hub/downloads", json=install_request(plan, manifest_sha256="f" * 64)
            ).status_code
            == 409
        )
        assert (
            api.post(
                "/api/model-hub/downloads",
                json={**install_request(plan), "url": "https://elsewhere.invalid/weights.gguf"},
            ).status_code
            == 422
        )
        assert not new_model["calls"]


def test_stop_and_explicit_resume_retain_the_new_pinned_manifest(new_model):
    with TestClient(app) as api:
        plan = reviewed_plan(api, new_model)
        accepted = api.post("/api/model-hub/downloads", json=install_request(plan)).json()
        identity = accepted["id"]
        assert api.post("/api/setup/downloads/" + identity + "/cancel").status_code == 200
        work()
        assert not new_model["calls"]
        resumed = api.post(
            "/api/setup/downloads/" + identity + "/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": accepted["run"]["id"]},
        )
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["entry"] == accepted["entry"]
        work()
        assert api.get("/api/setup/downloads/" + identity).json()["run"]["status"] == "succeeded"
        assert len(new_model["calls"]) == 1


def test_native_header_disagreement_cannot_publish_a_model(new_model):
    new_model["hub_entry"] = HubCandidate.model_validate(
        {**new_model["hub_entry"].model_dump(mode="json"), "attention_layers": 35}
    )
    with TestClient(app) as api:
        plan = reviewed_plan(api, new_model)
        accepted = api.post("/api/model-hub/downloads", json=install_request(plan))
        assert accepted.status_code == 202, accepted.text
        work()
        saved = api.get("/api/setup/downloads/" + accepted.json()["id"]).json()
        assert saved["run"]["status"] == "failed", saved
        assert "native source/architecture" in saved["run"]["error_message"]
    with control_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelFile)) == 0
        assert db.scalar(select(func.count()).select_from(ModelDefinition)) == 0


def test_unfitted_gpu_plan_is_blocked_before_transfer(new_model):
    new_model["hardware"]["gpus"] = []
    with TestClient(app) as api:
        plan = reviewed_plan(api, new_model)
        response = api.post("/api/model-hub/downloads", json=install_request(plan))
        assert response.status_code == 409 and "fitted GPU" in response.json()["detail"]
        assert not new_model["calls"]


def test_unknown_file_or_changed_observation_never_creates_install_plan(new_model):
    with TestClient(app) as api:
        created = api.post(
            "/api/model-hub/inspections",
            json={"client_request_id": str(uuid4()), "source": "publisher/new-model"},
        ).json()
        work()
        source = api.get("/api/runs/" + created["id"]).json()["metadata"]["source_inspection"]
        body = {
            "client_request_id": str(uuid4()),
            "inspection_run_id": created["id"],
            "filename": new_model["hub_entry"].filename,
            "observation_sha256": "f" * 64,
        }
        assert api.post("/api/model-hub/plans", json=body).status_code == 409
        body.update(observation_sha256=source["observation_sha256"], filename="../outside.gguf")
        assert api.post("/api/model-hub/plans", json=body).status_code == 422
        assert not new_model["calls"]
