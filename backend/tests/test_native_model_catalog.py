"""Guided native downloads keep engine/weights independent and preserve presets."""

from types import SimpleNamespace

import pytest
from ai_station_runner import native_model_verify as verifier
from app import model_setup
from app.api import app
from app.db import control_session_factory
from app.models import ModelDefinition
from app.native_llama_setup_client import NativeLlamaSetupClient
from app.setup_models import CANDIDATES
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_model_setup import request, work
from test_model_setup import setup_bridge as setup_bridge

PROFILE = "llamacpp-native-darwin-arm64-b12032-v2"


@pytest.fixture
def native_catalog(setup_bridge, monkeypatch, request):
    architecture = getattr(request, "param", "arm64")
    selected_profile = "llamacpp-native-darwin-" + architecture + "-b12032-v2"
    original = setup_bridge["entry"]
    item = original.model_copy(
        update={
            "id": original.id + "-macos-" + architecture.replace("_", "-") + "-cpu",
            "runtime_profile": selected_profile,
            "context_ceiling": 4096,
        }
    )
    monkeypatch.setattr(model_setup, "CANDIDATES", (item,))
    monkeypatch.setattr(model_setup, "candidate", lambda identity: item if identity == item.id else None)
    setup_bridge["hardware"].update(host={"system": "Darwin", "architecture": architecture}, gpus=[])
    state = {**setup_bridge, "entry": item, "sdk": True, "wrong_profile": False}
    monkeypatch.setattr(
        verifier, "platform", SimpleNamespace(system=lambda: "Darwin", machine=lambda: architecture)
    )
    monkeypatch.setattr(
        verifier.Environment,
        "resolve_id",
        lambda self, root, identity: {"observation": {"manifest_sha256": "a" * 64}},
    )

    def sdk(self, *, profile):
        return {
            "platform_supported": True,
            "sdk_prepared": state["sdk"],
            "environment": {
                "profile": "wrong" if state["wrong_profile"] else profile,
                "environment_id": "b" * 64,
            }
            if state["sdk"]
            else None,
        }

    monkeypatch.setattr(NativeLlamaSetupClient, "runtime_setup_catalog", sdk)
    return state


@pytest.mark.parametrize("native_catalog", ["arm64", "x86_64"], indirect=True)
def test_native_download_registers_verified_engine_reference_without_an_image(native_catalog):
    state = native_catalog
    with TestClient(app) as api:
        catalog = api.get("/api/setup/catalog").json()
        assert catalog["engine_profile"] == state["entry"].runtime_profile
        assert catalog["entries"][0]["recommendation"]["fits"] and catalog["entries"][0]["starter"]
        queued = api.post("/api/setup/downloads", json=request(state["entry"]))
        assert queued.status_code == 202, queued.text
        work()
        result = api.get("/api/setup/downloads/" + queued.json()["id"]).json()
        assert result["run"]["status"] == "succeeded", result
        assert result["progress"]["runtime_image_present"] is False
        assert result["progress"]["runtime_present"] and result["progress"]["ready_to_try"]
        with control_session_factory()() as db:
            definition = db.scalar(select(ModelDefinition))
            assert (
                definition.status == "registered" and definition.metadata_json["environment_id"] == "b" * 64
            )
        assert api.get("/api/setup/catalog").json()["entries"][0]["ready_to_try"]
        assert len(state["calls"]) == 1


def test_native_weights_can_precede_engine_and_activate_without_redownload(native_catalog):
    state = native_catalog
    state["sdk"] = False
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json={**request(state["entry"]), "download_only": True})
        assert response.status_code == 202, response.text
        work()
        result = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert result["run"]["status"] == "succeeded", result
        assert result["progress"]["ready_to_try"] is False
        assert result["progress"]["runtime_present"] is False
        with control_session_factory()() as db:
            definition = db.scalar(select(ModelDefinition))
            assert definition.status == "downloaded" and not definition.metadata_json.get("environment_id")
            identity = definition.id
        state["sdk"] = True
        verified = api.post(f"/api/models/definitions/{identity}/install", json={})
        assert verified.status_code == 202, verified.text
        work()
        run = api.get("/api/runs/" + verified.json()["id"]).json()
        assert run["status"] == "succeeded", run
        assert api.get("/api/setup/catalog").json()["entries"][0]["ready_to_try"]
        assert len(state["calls"]) == 1


def test_absent_or_foreign_sdk_cannot_mark_downloaded_weights_as_ready(native_catalog):
    state = native_catalog
    state["wrong_profile"] = True
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json=request(state["entry"]))
        work()
        result = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert result["run"]["status"] == "succeeded" and not result["progress"]["ready_to_try"]
        assert not api.get("/api/setup/catalog").json()["entries"][0]["ready_to_try"]


@pytest.mark.parametrize("architecture", ["arm64", "x86_64"])
def test_actual_catalog_filters_native_architecture_and_suggests_one_small_starter(
    native_catalog, monkeypatch, architecture
):
    monkeypatch.setattr(model_setup, "CANDIDATES", CANDIDATES)
    native_catalog["hardware"]["host"]["architecture"] = architecture
    with TestClient(app) as api:
        result = api.get("/api/setup/catalog").json()
    native = [entry for entry in result["entries"] if "darwin" in (entry.get("runtime_profile") or "")]
    assert len(native) == 6
    assert all(architecture in entry["runtime_profile"] for entry in native)
    assert len([entry for entry in native if entry["starter"]]) == 1
    assert any("14b" in entry["id"] for entry in native)
    assert all(not entry["recommendation"]["fits"] for entry in result["entries"] if entry not in native)
    assert "CPU" in next(entry for entry in native if entry["starter"])["name"]


def test_a_foreign_native_profile_is_rejected_before_even_a_files_only_transfer(native_catalog):
    state = native_catalog
    state["hardware"]["host"]["architecture"] = "x86_64"
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json={**request(state["entry"]), "download_only": True})
        work()
        result = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert result["run"]["status"] == "failed"
        assert not state["calls"]


def test_every_native_catalog_offer_survives_the_workers_strict_manifest_validation():
    from app.setup_models import Candidate

    for entry in CANDIDATES:
        assert Candidate.model_validate(entry.model_dump(mode="json")).id == entry.id
