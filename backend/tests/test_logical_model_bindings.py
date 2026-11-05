"""Distinct complete GGUFs sharing part one retain independent runtime identities."""

import hashlib
from copy import deepcopy

import pytest
from app.api import app
from app.db import control_session_factory
from app.hub_model_parts import annotate
from app.models import ModelDefinition, ModelFile
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_hub_split_installation import download, plan, work
from test_hub_split_installation import split_model as split_model
from test_model_setup import setup_bridge  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_publisher_observation(split_model, monkeypatch):  # noqa: F811
    from app import model_hub

    async def inspect(*args):
        return deepcopy(split_model["report"])

    monkeypatch.setattr(model_hub, "inspect_source", inspect)


def second_version(state):
    # Both files are structurally valid; this model changes a later weight.
    changed = state["objects"][state["rows"][1]["sha256"]][:-1] + b"\x01"
    row = state["rows"][1]
    row.update(sha256=hashlib.sha256(changed).hexdigest(), size_bytes=len(changed))
    state["objects"][row["sha256"]] = changed
    report = state["report"]
    report["revision"] = "b" * 40
    report["source_url"] = report["source_url"].replace("a" * 40, "b" * 40)
    report["license_url"] = report["license_url"].replace("a" * 40, "b" * 40)
    report["language_profile"]["source_revision"] = "b" * 40
    report["model_bundles"] = annotate(state["rows"])


def install_pair(api, state):
    first = download(api, plan(api, state))
    assert first["run"]["status"] == "succeeded", first
    second_version(state)
    second = download(api, plan(api, state))
    assert second["run"]["status"] == "succeeded", second["run"].get("error_message")
    return first, second


def test_shared_primary_has_two_stable_choices_without_copying_or_overwriting(split_model):  # noqa: F811
    with TestClient(app) as api:
        first = download(api, plan(api, split_model))
        with control_session_factory()() as db:
            original = deepcopy(db.get(ModelDefinition, first["definition_id"]).metadata_json)
        second_version(split_model)
        second = download(api, plan(api, split_model))
        assert second["run"]["status"] == "succeeded", second["run"].get("error_message")
        assert first["model_file_id"] == second["model_file_id"]
        assert first["model_key"] != second["model_key"]
        assert second["model_key"] == "llamacpp:" + second["definition_id"]
        keys = {row["model_key"] for row in api.get("/api/llama").json()["models"]}
        assert keys == {first["model_key"], second["model_key"]}
        choices = api.get("/api/chat/model-catalog").json()["models"]
        assert keys <= {row["model_ref"] for row in choices}
        # Re-inspecting the same immutable set reuses its logical choice.
        repeated = download(api, plan(api, split_model))
        assert repeated["run"]["status"] == "succeeded"
        assert repeated["model_key"] == second["model_key"]
    with control_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelFile)) == 1
        assert db.scalar(select(func.count()).select_from(ModelDefinition)) == 2
        assert db.get(ModelDefinition, first["definition_id"]).metadata_json == original
        later = db.get(ModelDefinition, second["definition_id"])
        assert later.binding_key and len(later.binding_key) == 64


def test_secondary_selection_loads_its_own_parts_and_cannot_reuse_sibling_runtime(split_model, monkeypatch):  # noqa: F811
    from app.llama import model_endpoint
    from app.local_provider import LocalChatProvider
    from app.providers import ProviderError

    requests = []

    def load(self, payload):
        from ai_station_runner.llama_runtime import Load

        Load.model_validate(payload)
        requests.append(payload)
        return {
            "status": "ready",
            "alive": True,
            "container_id": "c" * 64,
            "runner_id": "fixture",
            "gpus": payload["gpus"],
            "n_ctx": payload["context_size"],
        }

    async def stream(self, **kwargs):
        yield "Second model response."

    monkeypatch.setattr(RunnerClient, "load_llama", load)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as api:
        first, second = install_pair(api, split_model)
        conversation = api.post("/api/chat/conversations", json={"model": second["model_key"]}).json()
        response = api.post(
            "/api/chat/conversations/" + conversation["id"] + "/messages",
            json={"content": "Hello", "web_search": {"enabled": False}},
        )
        assert response.status_code == 202, response.text
        work()  # Native load prerequisite.
        work()  # Ordinary conversation.
        run = api.get("/api/runs/" + response.json()["id"]).json()
        assert run["status"] == "succeeded", run.get("error_message")
        assert len(requests) == 1
        assert requests[0]["model_bundle"]["parts"][1]["sha256"] == split_model["rows"][1]["sha256"]
        runtime = next(row for row in api.get("/api/llama").json()["instances"] if row["status"] == "ready")
        assert runtime["metadata"]["model_definition_id"] == second["definition_id"]
        with control_session_factory()() as db:
            assert model_endpoint(second["model_key"], db) == runtime["endpoint"]
            with pytest.raises(ProviderError):
                model_endpoint(first["model_key"], db)
        assert api.delete("/api/models/definitions/" + second["definition_id"]).status_code == 409
        invalid_preset = api.patch(
            "/api/models/definitions/" + second["definition_id"], json={"cache_type": "f16"}
        )
        assert invalid_preset.status_code == 422
        # A mismatched typed file/definition coordinate is rejected before queueing.
        bad = api.post(
            "/api/llama/load",
            json={
                "model_file_id": first["model_file_id"],
                "model_definition_id": first["definition_id"],
                "gpus": [7],
                "cache_type": "q8_0",
            },
        )
        assert bad.status_code == 422


def test_removed_default_cannot_be_replaced_by_a_sibling_and_can_be_restored(split_model):  # noqa: F811
    with TestClient(app) as api:
        first, second = install_pair(api, split_model)
        assert api.delete("/api/models/definitions/" + first["definition_id"]).status_code == 204
        assert {row["model_key"] for row in api.get("/api/llama").json()["models"]} == {second["model_key"]}
        with control_session_factory()() as db:
            from app.model_selection import resolve

            assert resolve(db, first["model_key"]) == (None, None)
            assert db.get(ModelDefinition, first["definition_id"]).status == "removed"
        blocked = api.post(
            "/api/llama/load",
            json={"model_file_id": first["model_file_id"], "gpus": [7], "cache_type": "q8_0"},
        )
        assert blocked.status_code == 409
        repeated = download(api, plan(api, split_model))
        assert repeated["model_key"] == second["model_key"]
        restored = api.post("/api/models/definitions/" + first["definition_id"] + "/install", json={})
        assert restored.status_code == 202, restored.text
        work()
        restored_run = api.get("/api/runs/" + restored.json()["id"]).json()
        assert restored_run["status"] == "succeeded", restored_run.get("error_message")
        assert {row["model_key"] for row in api.get("/api/llama").json()["models"]} == {
            first["model_key"],
            second["model_key"],
        }


def test_member_can_use_secondary_binding_without_private_installation_access(
    split_model,
    accounts,
    monkeypatch,  # noqa: F811
):  # noqa: F811
    from app.local_provider import LocalChatProvider

    owner, alice, bob = accounts
    first, second = install_pair(owner, split_model)
    requests = []

    def load(self, payload):
        requests.append(payload)
        return {
            "status": "ready",
            "alive": True,
            "runner_id": "fixture",
            "container_id": "c" * 64,
            "gpus": payload["gpus"],
            "n_ctx": payload["context_size"],
        }

    async def stream(self, **kwargs):
        yield "Shared model, private conversation."

    monkeypatch.setattr(RunnerClient, "load_llama", load)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    for member in [alice, bob]:
        conversation = member.post("/api/chat/conversations", json={"model": second["model_key"]}).json()
        reply = member.post(
            "/api/chat/conversations/" + conversation["id"] + "/messages",
            json={"content": "Private prompt", "web_search": {"enabled": False}},
        )
        assert reply.status_code == 202, reply.text
        work()
        work()
        assert member.get("/api/runs/" + reply.json()["id"]).json()["status"] == "succeeded"
        assert owner.get("/api/runs/" + reply.json()["id"]).status_code == 404
    assert len(requests) == 1  # Bob reuses Alice's actual logical runtime.
    assert alice.get("/api/runs/" + second["run"]["id"]).status_code == 404
    shared = alice.get("/api/models/" + first["model_file_id"])
    assert shared.status_code == 200
    assert all(item["last_verify_run_id"] is None for item in shared.json()["definitions"])
    assert alice.delete("/api/models/definitions/" + second["definition_id"]).status_code == 403
