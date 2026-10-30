"""Auto model selection shares measured context without sharing private Runs."""

import json

import pytest
from app.coding_model_routing import select_coding_model
from app.data_access import DataScope, ScopedSession
from app.db import control_session_factory, get_engine
from app.events import append_event
from app.models import Run, RuntimeInstance
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
