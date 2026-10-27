import pytest
from app.coding_model_routing import select_coding_model
from app.events import append_event
from app.llama import update_instance
from app.models import ModelFile, RuntimeInstance
from app.providers import ProviderError
from app.runner_client import RunnerClient
from app.runs import create_run, create_task


def candidate(session, *, name="Coder-27B.gguf", context=100352, size=8 * 1024**3, trained=262144):
    model = ModelFile(
        host_path="/models/" + name,
        filename=name,
        size_bytes=size,
        mtime=1,
        category="llm",
        format="gguf",
        availability="present",
    )
    session.add(model)
    session.flush()
    task = create_task(session, title="Load", prompt="", capability="runtime.load")
    load = create_run(session, task, run_type="runtime", capability="runtime.load", executor_type="llamacpp")
    load.status = "succeeded"
    runtime = RuntimeInstance(
        runtime_key="llama.cpp",
        name=name,
        ownership="managed",
        status="stopped",
        metadata_json={
            "model_file_id": model.id,
            "load_run_id": load.id,
            "model_size_bytes": size,
            "model_mtime": 1,
            "gpus": [2, 7],
            "context_size": context,
            "observation": {"n_ctx": context},
            "context_fit": "ok",
            "cache_type": "q8_0",
            "context_profile": {
                "trained_context": trained,
                "q8_kv_bytes_per_token": 128 * 1024,
                "state_reserve_mib": 0,
            },
        },
    )
    session.add(runtime)
    session.flush()
    return model, runtime


@pytest.fixture
def hardware(monkeypatch):
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {
            "gpus": [{"index": 2, "memory_total_mib": 12288}, {"index": 7, "memory_total_mib": 12288}]
        },
    )


def test_auto_routes_to_proven_local_context_and_preserves_gpu_selection(session, hardware):
    model, _ = candidate(session)
    result = select_coding_model(session)
    assert result["model"] == "llamacpp:" + model.id
    assert result["context_size"] >= 100000
    assert result["context_verified"] and result["gpus"] == [2, 7]


@pytest.mark.parametrize("change", ["changed_file", "unknown_runtime", "short_context", "missing_gpu"])
def test_auto_rejects_unqualified_or_changed_context_without_external_fallback(
    session, hardware, monkeypatch, change
):
    model, runtime = candidate(session)
    if change == "changed_file":
        model.mtime = 2
    if change == "unknown_runtime":
        runtime.status = "unknown"
    if change == "short_context":
        runtime.metadata_json = {
            **runtime.metadata_json,
            "context_profile": {"trained_context": 32768},
            "context_size": 32768,
        }
    if change == "missing_gpu":
        monkeypatch.setattr(
            RunnerClient, "hardware", lambda _: {"gpus": [{"index": 2, "memory_total_mib": 12288}]}
        )
    with pytest.raises(ProviderError, match="100k"):
        select_coding_model(session)


def test_auto_prefer_proven_coder_over_unproven_allocation(session, hardware):
    model, _ = candidate(session)
    other, runtime = candidate(session, name="Larger-32B.gguf", context=32768, size=9 * 1024**3)
    runtime.metadata_json = {
        **runtime.metadata_json,
        "context_profile": {"trained_context": 262144, "q8_kv_bytes_per_token": 64 * 1024},
    }
    assert select_coding_model(session)["model"] == "llamacpp:" + model.id


def test_auto_uses_observed_allocation_instead_of_larger_requested_settings(session, hardware):
    model, _ = candidate(session, name="Ready-9B.gguf", context=129280, size=7 * 1024**3)
    _, larger = candidate(session, name="Larger-27B.gguf", context=131072, size=9 * 1024**3)
    larger.metadata_json = {**larger.metadata_json, "observation": {"n_ctx": 65536}}
    selected = select_coding_model(session)
    assert selected["model"] == "llamacpp:" + model.id
    assert selected["context_verified"] and selected["context_size"] == 129280


@pytest.mark.parametrize("actual", [None, False, 0, "131072"])
def test_missing_or_invalid_observation_never_outranks_a_verified_model(session, hardware, actual):
    model, _ = candidate(session, name="Qualified-9B.gguf", context=129280, size=7 * 1024**3)
    _, runtime = candidate(session, name="Unverified-27B.gguf", context=131072, size=9 * 1024**3)
    runtime.metadata_json = {**runtime.metadata_json, "observation": {"n_ctx": actual}}
    selected = select_coding_model(session)
    assert selected["model"] == "llamacpp:" + model.id and selected["context_verified"]


def test_auto_preserves_a_sufficient_observed_context_without_speculative_upgrade(session, hardware):
    _, runtime = candidate(session, context=129280)
    runtime.status = "ready"
    selected = select_coding_model(session)
    assert selected["context_size"] == 129280 and selected["context_verified"]


def stopped_candidate(session):
    model, runtime = candidate(session, name="Stopped-9B.gguf", context=129280, size=7 * 1024**3)
    payload = {
        "instance_id": runtime.id,
        "gpus": [2, 7],
        "cache_type": "q8_0",
        "context_size": 129280,
        "n_ctx": 129280,
    }
    runtime.status = "ready"
    update_instance(session, runtime, {"status": "stopped", "alive": False})
    assert "n_ctx" not in runtime.metadata_json["observation"]
    return model, runtime, payload


def test_real_stop_observation_retains_successful_load_measurement_for_auto(session, hardware):
    model, runtime, payload = stopped_candidate(session)
    append_event(session, runtime.metadata_json["load_run_id"], "runtime.ready", payload)
    candidate(session, name="Larger-27B.gguf", context=65536, size=9 * 1024**3)
    chosen = select_coding_model(session)
    assert chosen["model"] == "llamacpp:" + model.id
    assert chosen["context_verified"] and chosen["context_size"] == 129280


@pytest.mark.parametrize(
    "change",
    ["instance", "gpus", "cache", "missing_actual", "string_actual", "zero_actual", "failed_load", "ready"],
)
def test_stopped_context_proof_requires_matching_successful_native_measurement(session, hardware, change):
    from app.models import Run

    _, runtime, payload = stopped_candidate(session)
    if change == "instance":
        payload["instance_id"] = "another-instance"
    elif change == "gpus":
        payload["gpus"] = [2]
    elif change == "cache":
        payload["cache_type"] = "f16"
    elif change == "missing_actual":
        payload.pop("n_ctx")
    elif change == "string_actual":
        payload["n_ctx"] = "129280"
    elif change == "zero_actual":
        payload["n_ctx"] = 0
    elif change == "failed_load":
        session.get(Run, runtime.metadata_json["load_run_id"]).status = "failed"
    elif change == "ready":
        runtime.status = "ready"
    append_event(session, runtime.metadata_json["load_run_id"], "runtime.ready", payload)
    alternative, _ = candidate(session, name="Qualified-8B.gguf", context=129280, size=6 * 1024**3)
    assert select_coding_model(session)["model"] == "llamacpp:" + alternative.id


def test_auto_api_is_read_only_and_coding_snapshots_actual_model_before_dispatch(
    session, hardware, monkeypatch
):
    from app.api import app
    from app.models import Project, Run
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    model, _ = candidate(session)
    project = Project(name="Example", repo_path="/allowed/example")
    session.add(project)
    session.commit()
    monkeypatch.setattr(RunnerClient, "load_llama", lambda *_: pytest.fail("Model loading belongs to worker"))
    before = session.scalar(select(func.count()).select_from(Run))
    project_id, updated_at, model_id = project.id, project.updated_at.isoformat(), model.id
    session.commit()
    with TestClient(app) as client:
        preview = client.get("/api/coding/auto-model")
        assert preview.status_code == 200 and preview.json()["available"]
        assert session.scalar(select(func.count()).select_from(Run)) == before
        session.commit()
        response = client.post(
            "/api/coding/local",
            json={
                "project_id": project_id,
                "expected_updated_at": updated_at,
                "prompt": "Build a useful app",
                "explore": True,
            },
        )
        assert response.status_code == 202, response.text
        selected = response.json()["parameters"]["local_coding"]
        assert selected["model"] == "llamacpp:" + model_id
        assert selected["model_selection"]["requested"] == "auto"
        assert selected["model_selection"]["context_verified"]
        assert "external_ai" not in response.json()["effective_permissions"]


@pytest.mark.parametrize("context,allowed", [(32768, False), (100352, True)])
def test_auto_dispatch_requires_actual_ready_context_not_just_a_prior_estimate(
    session, hardware, monkeypatch, context, allowed
):
    from app.local_coding import LocalProposalExecutor
    from app.native_job_executor import NativeJobExecutor

    model, runtime = candidate(session)
    selected = select_coding_model(session)
    runtime.status = "ready"
    runtime.endpoint = "http://127.0.0.1:12345/v1"
    runtime.metadata_json = {**runtime.metadata_json, "context_size": context}
    task = create_task(session, title="Coding", prompt="", capability="coding.local")
    run = create_run(
        session,
        task,
        run_type="coding",
        capability="coding.local",
        executor_type="local_proposal",
        parameters={"endpoint": runtime.endpoint, "model_selection": {"requested": "auto", **selected}},
    )
    monkeypatch.setattr(NativeJobExecutor, "execute", lambda *_: "dispatched")
    if allowed:
        assert LocalProposalExecutor().execute(session, run) == "dispatched"
    else:
        with pytest.raises(ProviderError, match="100k"):
            LocalProposalExecutor().execute(session, run)
