"""Auto model selection shares measured context without sharing private Runs."""

import json

import pytest
from app.coding_model_routing import select_coding_model
from app.data_access import DataScope, ScopedSession
from app.data_context import bind_data_scope
from app.db import control_session_factory, get_engine
from app.events import append_event
from app.model_registry import file_dict
from app.models import ModelDefinition, ModelFile, Run, RuntimeInstance
from app.runner_client import RunnerClient
from app.runtime_coordination import runtime_coding_facts
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_runtime_coordination import runtime
from test_llama import managed as managed


@pytest.mark.parametrize("status", ["ready", "stopped"])
def test_auto_can_select_a_foreign_models_verified_context_without_exposing_loader_or_events(
    accounts, managed, monkeypatch, status
):
    owner, alice, _ = accounts
    instance_id, _ = runtime(owner, managed[0])
    marker = alice.post("/api/testing/runs", json={"title": "Synthetic own model-selection scope"}).json()[
        "id"
    ]
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {
            "gpus": [{"index": 2, "memory_total_mib": 12288}, {"index": 7, "memory_total_mib": 12288}]
        },
    )
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, marker).owner_id
        instance = queue.get(RuntimeInstance, instance_id)
        loader_id = instance.metadata_json["load_run_id"]
        loader = queue.get(Run, loader_id)
        loader.parameters = {**loader.parameters, "private_prompt": "Synthetic private producer marker"}
        instance.status = status
        instance.metadata_json = {
            **instance.metadata_json,
            "gpus": [2, 7],
            "context_size": 100352,
            "cache_type": "q8_0",
            "context_fit": "ok",
            "observation": {"n_ctx": 100352} if status == "ready" else {"status": "stopped", "alive": False},
            "context_profile": {
                "trained_context": 262144,
                "q8_kv_bytes_per_token": 128 * 1024,
                "state_reserve_mib": 0,
            },
        }
        append_event(
            queue,
            loader_id,
            "runtime.ready",
            {
                "instance_id": instance_id,
                "gpus": [2, 7],
                "cache_type": "q8_0",
                "n_ctx": 100352,
                "private_log": "Synthetic private producer event marker",
            },
        )
        queue.commit()
    with ScopedSession(bind=get_engine(), scope=DataScope(owner_id)) as session:
        assert session.get(Run, loader_id) is None
        facts = runtime_coding_facts(session, session.get(RuntimeInstance, instance_id))
        assert loader_id not in json.dumps(facts, default=str)
        assert "Synthetic private producer" not in json.dumps(facts, default=str)
        selected = select_coding_model(session)
        assert selected["model"] == "llamacpp:" + managed[0]
        assert selected["context_verified"] and selected["context_size"] == 100352
        assert selected["gpus"] == [2, 7]
        encoded = json.dumps(selected)
        assert loader_id not in encoded and "Synthetic private producer" not in encoded
    assert alice.get("/api/runs/" + loader_id + "/events").status_code == 404


def test_shared_model_definition_does_not_publish_another_accounts_private_verification_run(
    accounts, managed
):
    owner, alice, _ = accounts
    marker = owner.post("/api/testing/runs", json={"title": "Synthetic private model verification"}).json()[
        "id"
    ]
    with control_session_factory()() as queue:
        definition = ModelDefinition(
            name="Synthetic shared model", file_id=managed[0], last_verify_run_id=marker
        )
        queue.add(definition)
        queue.commit()
        definition_id = definition.id
    own = owner.get("/api/models/definitions/" + definition_id)
    assert own.status_code == 200 and own.json()["last_verify_run_id"] == marker
    for path in (
        "/api/models/definitions",
        "/api/models/definitions/" + definition_id,
        "/api/models/" + managed[0],
    ):
        response = alice.get(path)
        assert response.status_code == 200, response.text
        assert marker not in response.text
    inspected = owner.get(
        "/api/models/definitions/" + definition_id, headers={"X-AI-Station-Inspect-All": "true"}
    )
    assert inspected.status_code == 200 and inspected.json()["last_verify_run_id"] == marker


def test_shared_model_files_hide_foreign_discovery_activity_but_retain_hardware_metadata(accounts, managed):
    owner, alice, _ = accounts
    marker = owner.post("/api/testing/runs", json={"title": "Synthetic private discovery"}).json()["id"]
    with control_session_factory()() as queue:
        queue.get(ModelFile, managed[0]).last_scan_run_id = marker
        queue.commit()
    for path in ("/api/models", "/api/models/" + managed[0]):
        response = alice.get(path)
        assert response.status_code == 200 and marker not in response.text
    assert alice.get("/api/models/" + managed[0]).json()["host_path"] == "/models/model.gguf"
    assert alice.get("/api/runs/" + marker).status_code == 404
    own = owner.get("/api/models/" + managed[0])
    assert own.status_code == 200 and own.json()["last_scan_run_id"] == marker
    alice_id = alice.get("/api/auth").json()["user"]["id"]
    with control_session_factory()() as coordination:
        row = coordination.get(ModelFile, managed[0])
        with bind_data_scope(DataScope(alice_id)):
            assert file_dict(row)["last_scan_run_id"] is None
        coordination.expunge(row)
        with bind_data_scope(DataScope(alice_id)):
            assert file_dict(row)["last_scan_run_id"] is None
