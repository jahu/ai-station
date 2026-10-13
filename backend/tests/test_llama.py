import asyncio
from datetime import timedelta

import httpx
import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.llama import instances
from app.local_provider import LocalChatProvider
from app.models import ModelFile, Run
from app.recovery import recover_stale
from app.resources import active_locks
from app.runner_client import RunnerClient
from app.runs import claim_next, request_cancel, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def managed(monkeypatch):
    records = {}
    monkeypatch.setattr(
        RunnerClient, "verify_model", lambda _, body: {"present": True, "matches_observation": True}
    )
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"gpus": [{"index": 2}, {"index": 7}]})

    def load(_, body):
        records.setdefault(body["instance_id"], {"status": "ready", "alive": True, "gpus": body["gpus"]})
        return records[body["instance_id"]]

    def stop(_, instance_id):
        records[instance_id] = {"status": "stopped", "alive": False}
        return records[instance_id]

    monkeypatch.setattr(RunnerClient, "load_llama", load)
    monkeypatch.setattr(RunnerClient, "inspect_llama", lambda _, id: records[id])
    monkeypatch.setattr(RunnerClient, "stop_llama", stop)
    with session_factory()() as session:
        model = ModelFile(
            host_path="/models/model.gguf",
            filename="model.gguf",
            format="gguf",
            category="llm",
            availability="present",
            size_bytes=1000,
            mtime=1,
        )
        session.add(model)
        session.commit()
        model_id = model.id
    return model_id, records


def load(client, model):
    response = client.post("/api/llama/load", json={"model_file_id": model, "gpus": [2, 7]})
    assert response.status_code == 202, response.text
    return response.json()


def tick_once():
    with session_factory()() as session:
        return tick(session, "llama-test")


def test_load_holds_both_gpus_until_stop_and_chat_uses_private_instance(managed, monkeypatch):
    model_id, records = managed
    with TestClient(app) as client:
        run = load(client, model_id)
        tick_once()
        instance = client.get("/api/llama").json()["instances"][0]
        assert instance["status"] == "ready"
        with session_factory()() as session:
            assert active_locks(session) == {"gpu:2", "gpu:7"}
            assert session.get(Run, run["id"]).status == "succeeded"
        conv = client.post("/api/chat/conversations", json={"model": "llamacpp:" + model_id}).json()
        chat = client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"}).json()
        assert chat["parameters"]["endpoint"] == "llamacpp:" + instance["id"]
        assert client.post(f"/api/llama/{instance['id']}/stop").status_code == 409
        seen = []

        async def stream(self, **params):
            seen.append(params)
            yield "Hello from llama.cpp"

        monkeypatch.setattr(LocalChatProvider, "stream", stream)
        tick_once()
        assert seen[0]["model"] == "llamacpp:" + model_id
        assert client.post(f"/api/llama/{instance['id']}/stop").status_code == 202
        tick_once()
        with session_factory()() as session:
            assert not active_locks(session)
        assert (
            client.post(
                f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"}
            ).status_code
            == 202
        )
        assert records[instance["id"]]["alive"] is False


def test_recovery_keeps_reservations_and_resumes_same_runtime(managed):
    model_id, records = managed
    with TestClient(app) as client:
        queued = load(client, model_id)
        with session_factory()() as session:
            run = claim_next(session, "disappeared")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            from app.llama import reserve

            reserve(session, run, [2, 7])
            run.metadata_json = {"dispatch_attempted": True}
            run.lease_expires_at = utcnow() - timedelta(seconds=10)
            session.commit()
            recover_stale(session)
            session.commit()
            assert active_locks(session) == {"gpu:2", "gpu:7"}
            assert session.get(Run, queued["id"]).status == "queued"
        tick_once()
        assert len(records) == 1
        with session_factory()() as session:
            assert session.get(Run, queued["id"]).status == "succeeded"


def test_cancel_resumed_loading_stops_owned_instance(managed):
    model_id, records = managed
    with TestClient(app) as client:
        load(client, model_id)
        with session_factory()() as session:
            run = claim_next(session, "old-worker")
            request_cancel(session, run)
            run.metadata_json = {"dispatch_attempted": True}
            run.lease_expires_at = utcnow() - timedelta(seconds=10)
            session.commit()
            recover_stale(session)
            session.commit()
        tick_once()
        with session_factory()() as session:
            assert session.scalar(select(Run)).status == "canceled"
            assert instances(session)[0].status == "stopped"
            assert not active_locks(session)
        assert all(not info["alive"] for info in records.values())


def test_selected_model_stream_rewrites_only_owned_alias_and_uses_runner_uds(managed, monkeypatch):
    model_id, _ = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
    with session_factory()() as session:
        instance = instances(session)[0]
        instance_id, endpoint = instance.id, instance.endpoint
    seen = []
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        assert isinstance(kwargs.pop("transport"), httpx.AsyncHTTPTransport)

        async def handler(request):
            seen.append(request)
            return httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
            )

        return real_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async def consume():
        return [
            x
            async for x in LocalChatProvider().stream(
                endpoint=endpoint,
                messages=[{"role": "user", "content": "Hi"}],
                model="llamacpp:" + model_id,
                temperature=0,
                max_tokens=10,
            )
        ]

    assert asyncio.run(consume()) == ["ok"]
    assert str(seen[0].url) == f"http://runner/v1/llama/{instance_id}/chat/completions"
    import json

    assert json.loads(seen[0].content)["model"] == instance_id


def test_cancel_queued_resumed_load_waits_for_owned_stop(managed):
    model_id, records = managed
    with TestClient(app) as client:
        queued = load(client, model_id)
        with session_factory()() as session:
            run = session.get(Run, queued["id"])
            run.metadata_json = {"dispatch_attempted": True}
            request_cancel(session, run)
            session.commit()
            assert run.status == "queued"
            assert run.metadata_json["cancel_on_resume"] is True
        tick_once()
        with session_factory()() as session:
            assert session.get(Run, queued["id"]).status == "canceled"
        assert all(not info["alive"] for info in records.values())


def test_canceled_stop_reconciles_live_runtime_and_keeps_gpu_reservations(managed):
    from app.llama import reconcile

    model_id, _ = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        instance = client.get("/api/llama").json()["instances"][0]
        stop = client.post(f"/api/llama/{instance['id']}/stop").json()
        assert client.post(f"/api/runs/{stop['id']}/cancel").status_code == 200
        with session_factory()() as session:
            reconcile(session, RunnerClient())
            assert instances(session)[0].status == "ready"
            assert active_locks(session) == {"gpu:2", "gpu:7"}


def test_cancel_during_model_load_stops_and_releases_both_gpus(managed, monkeypatch):
    model_id, records = managed

    def loading(_, body):
        records[body["instance_id"]] = {"status": "loading", "alive": True}
        with session_factory()() as session:
            request_cancel(session, session.get(Run, body["run_id"]))
            session.commit()
        return records[body["instance_id"]]

    monkeypatch.setattr(RunnerClient, "load_llama", loading)
    with TestClient(app) as client:
        queued = load(client, model_id)
        tick_once()
        with session_factory()() as session:
            assert session.get(Run, queued["id"]).status == "canceled"
            assert not active_locks(session)
        assert all(not info["alive"] for info in records.values())


def test_conversations_share_pending_load_and_reload_saved_preset(managed, monkeypatch):
    from app.models import RunDependency

    model_id, _ = managed

    async def stream(self, **params):
        yield "Ready"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        initial = load(client, model_id)
        conversations = [
            client.post("/api/chat/conversations", json={"model": "llamacpp:" + model_id}).json()
            for _ in range(2)
        ]
        chats = [
            client.post(f"/api/chat/conversations/{c['id']}/messages", json={"content": "Hello"}).json()
            for c in conversations
        ]
        with session_factory()() as session:
            assert len(list(session.scalars(select(RunDependency)))) == 2
        assert tick_once() == initial["id"]
        for chat in chats:
            assert tick_once() == chat["id"]
        instance = client.get("/api/llama").json()["instances"][0]
        stop = client.post(f"/api/llama/{instance['id']}/stop").json()
        # Queue another turn while stopping. It must wait for stop, then fresh load.
        queued = client.post(
            f"/api/chat/conversations/{conversations[0]['id']}/messages", json={"content": "Again"}
        )
        assert queued.status_code == 202, queued.text
        assert tick_once() == stop["id"]
        reload_id = tick_once()
        with session_factory()() as session:
            reload = session.get(Run, reload_id)
            assert reload.executor_type == "llama_load"
            assert reload.parameters["gpus"] == [2, 7]
            assert reload.parameters["context_size"] == 4096
            assert reload.parameters["cache_type"] == "f16"
            assert reload.status == "succeeded"
        assert tick_once() == queued.json()["id"]
        assert len(client.get("/api/llama").json()["instances"]) == 2


def test_image_evicts_only_idle_owned_model_and_waits_for_stop(managed):
    from app.llama import evict_idle_models
    from app.models import RuntimeInstance
    from app.runs import create_run, create_task

    model_id, _ = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        with session_factory()() as session:
            session.add(
                RuntimeInstance(
                    runtime_key="ollama",
                    name="external",
                    ownership="external",
                    status="ready",
                    metadata_json={"gpus": [2, 7]},
                )
            )
            task = create_task(session, title="image", prompt="", capability="image.generate")
            image = create_run(
                session,
                task,
                run_type="image",
                capability="image.generate",
                executor_type="fake",
                requested_gpu="auto",
            )
            evict_idle_models(session, image, [2, 7])
            session.commit()
            image_id = image.id
            assert active_locks(session) == {"gpu:2", "gpu:7"}
        stop_id = tick_once()
        with session_factory()() as session:
            assert session.get(Run, stop_id).executor_type == "llama_stop"
            assert not active_locks(session)
            assert (
                session.scalar(select(RuntimeInstance).where(RuntimeInstance.name == "external")).status
                == "ready"
            )
        assert tick_once() == image_id


def test_model_with_pending_consumer_cannot_be_evicted(managed):
    from app.llama import evict_idle_models
    from app.runs import create_run, create_task

    model_id, _ = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        conv = client.post("/api/chat/conversations", json={"model": "llamacpp:" + model_id}).json()
        client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"})
        with session_factory()() as session:
            task = create_task(session, title="image", prompt="", capability="image.generate")
            image = create_run(
                session,
                task,
                run_type="image",
                capability="image.generate",
                executor_type="fake",
                requested_gpu="auto",
            )
            evict_idle_models(session, image, [2, 7])
            assert instances(session)[0].status == "ready"
            assert not list(session.scalars(select(Run).where(Run.executor_type == "llama_stop")))


def test_loading_another_model_evicts_idle_runtime(managed):
    model_id, _ = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        with session_factory()() as session:
            other = ModelFile(
                host_path="/models/other.gguf",
                filename="other.gguf",
                format="gguf",
                category="llm",
                availability="present",
                size_bytes=1000,
                mtime=1,
            )
            session.add(other)
            session.commit()
            other_id = other.id
        second = load(client, other_id)
        assert tick_once() == second["id"]  # requeues behind the owned stop
        stop_id = tick_once()
        with session_factory()() as session:
            assert session.get(Run, stop_id).executor_type == "llama_stop"
        assert tick_once() == second["id"]
        with session_factory()() as session:
            assert session.get(Run, second["id"]).status == "succeeded"
            assert active_locks(session) == {"gpu:2", "gpu:7"}
            assert sorted(i.status for i in instances(session)) == ["ready", "stopped"]


@pytest.mark.parametrize("filename", ["mmproj-model.gguf", "model-MMProj-F16.gguf"])
def test_vision_projector_is_not_a_standalone_chat_model(filename):
    with session_factory()() as session:
        model = ModelFile(
            host_path="/models/" + filename,
            filename=filename,
            format="gguf",
            category="llm",
            availability="present",
            size_bytes=1000,
            mtime=1,
        )
        session.add(model)
        session.commit()
        model_id = model.id
    with TestClient(app) as client:
        assert client.get("/api/llama").json()["models"] == []
        assert client.post("/api/llama/load", json={"model_file_id": model_id, "gpus": []}).status_code == 422


def test_explicit_media_action_does_not_load_unused_planner_model(managed):
    model_id, _ = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        instance = client.get("/api/llama").json()["instances"][0]
        client.post(f"/api/llama/{instance['id']}/stop")
        tick_once()
        conversation = client.post(
            "/api/chat/conversations",
            json={"model": "llamacpp:" + model_id, "execution_mode": "orchestrator"},
        ).json()
        result = client.post(
            f"/api/chat/conversations/{conversation['id']}/messages",
            json={"content": "A forest", "action": "image.generate"},
        )
        assert result.status_code == 202, result.text
        assert tick_once() == result.json()["id"]
        with session_factory()() as session:
            assert len(list(session.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 1
            assert session.scalar(select(Run).where(Run.executor_type == "photo_pipe")).status == "queued"


WEIGHTS_27B = int(15.4 * 1024**3)


def two_12gb():
    from app.llama import fit_coding_context

    return fit_coding_context(gpus=[2, 7], size_bytes=WEIGHTS_27B, gpu_memory_mib=[12288.0, 12288.0])


@pytest.fixture
def coding_fit(managed, monkeypatch):
    model_id, records = managed
    monkeypatch.setattr(
        "app.llama.gpu_memory_totals", lambda gpus: [12288.0, 12288.0] if list(gpus) == [2, 7] else None
    )
    with session_factory()() as session:
        session.get(ModelFile, model_id).size_bytes = WEIGHTS_27B
        session.commit()
    return model_id, records


def proposal(session, model_id):
    from app.runs import create_run, create_task

    task = create_task(session, title="code", prompt="website", capability="coding.local")
    return create_run(
        session,
        task,
        run_type="coding",
        capability="coding.local",
        executor_type="local_proposal",
        parameters={"model": "llamacpp:" + model_id},
    )


def test_two_12gb_27b_q8_does_not_select_128k():
    from app.llama import CODING_CONTEXT_FALLBACK, fit_coding_context

    fitted = two_12gb()
    assert fitted != 131072
    assert 16384 <= fitted <= 32768
    assert (
        fit_coding_context(gpus=[0, 1], size_bytes=WEIGHTS_27B, gpu_memory_mib=[24576.0, 24576.0]) == 131072
    )
    assert fit_coding_context(gpus=[], size_bytes=WEIGHTS_27B, gpu_memory_mib=[], ceiling=131072) == 4096
    assert (
        fit_coding_context(gpus=[2, 7], size_bytes=WEIGHTS_27B, gpu_memory_mib=None)
        == CODING_CONTEXT_FALLBACK
    )
    assert (
        fit_coding_context(gpus=[2, 7], size_bytes=WEIGHTS_27B, gpu_memory_mib=None, proven_success=32768)
        == 32768
    )
    smaller = fit_coding_context(
        gpus=[2, 7], size_bytes=WEIGHTS_27B, gpu_memory_mib=[12288.0, 12288.0], failed_sizes=[fitted]
    )
    assert smaller < fitted
    assert smaller != 131072


def test_q8_load_fits_instead_of_forcing_128k(coding_fit):
    model_id, _ = coding_fit
    with TestClient(app) as client:
        response = client.post(
            "/api/llama/load",
            json={"model_file_id": model_id, "gpus": [2, 7], "context_size": 131072, "cache_type": "q8_0"},
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            run = session.get(Run, response.json()["id"])
            from app.models import RuntimeInstance

            instance = session.get(RuntimeInstance, run.parameters["instance_id"])
            assert run.parameters["context_size"] == two_12gb()
            assert run.parameters["cache_type"] == "q8_0"
            assert run.parameters["requested_context_size"] == 131072
            assert instance.metadata_json["requested_context_size"] == 131072


def test_q8_load_does_not_forward_fit_metadata_to_runner(coding_fit, monkeypatch):
    model_id, records = coding_fit
    seen = []

    def load(_, body):
        seen.append(body)
        records[body["instance_id"]] = {"status": "ready", "alive": True, "gpus": body["gpus"]}
        return records[body["instance_id"]]

    monkeypatch.setattr(RunnerClient, "load_llama", load)
    monkeypatch.setattr(RunnerClient, "inspect_llama", lambda _, identity: records[identity])
    with TestClient(app) as client:
        client.post(
            "/api/llama/load",
            json={"model_file_id": model_id, "gpus": [2, 7], "context_size": 131072, "cache_type": "q8_0"},
        )
        tick_once()
    assert seen
    assert "requested_context_size" not in seen[0]
    assert seen[0]["context_size"] == two_12gb()
    assert seen[0]["cache_type"] == "q8_0"


def test_invalid_cache_type_and_context_rejected(managed):
    model_id, _ = managed
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/llama/load", json={"model_file_id": model_id, "gpus": [2, 7], "cache_type": "q4_0"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/llama/load", json={"model_file_id": model_id, "gpus": [2, 7], "context_size": 1000}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/llama/load", json={"model_file_id": model_id, "gpus": [2, 7], "context_size": 262400}
            ).status_code
            == 422
        )


def test_idle_smaller_runtime_upgrades_to_fitted_q8(coding_fit):
    from app.llama import prepare_consumer
    from app.models import RunDependency, RuntimeInstance

    model_id, _ = coding_fit
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        with session_factory()() as session:
            previous = instances(session)[0]
            run = proposal(session, model_id)
            prepare_consumer(session, run)
            session.commit()
            loads = list(session.scalars(select(Run).where(Run.executor_type == "llama_load")))
            assert len(loads) == 2
            fresh = next(item for item in loads if item.parameters["instance_id"] != previous.id)
            assert fresh.parameters["context_size"] == two_12gb()
            assert fresh.parameters["cache_type"] == "q8_0"
            assert session.get(RuntimeInstance, previous.id).status == "stopping"
            assert session.scalar(
                select(RunDependency).where(
                    RunDependency.run_id == fresh.id,
                    RunDependency.prerequisite_id == previous.metadata_json["operation_run_id"],
                )
            )
            assert session.scalar(
                select(RunDependency).where(
                    RunDependency.run_id == run.id, RunDependency.prerequisite_id == fresh.id
                )
            )


def test_active_consumer_blocks_coding_context_upgrade(coding_fit):
    from app.llama import prepare_consumer
    from app.providers import ProviderError
    from app.runs import create_run, create_task

    model_id, _ = coding_fit
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        with session_factory()() as session:
            instance = instances(session)[0]
            busy = create_task(session, title="chat", prompt="hi", capability="chat.completion")
            create_run(
                session,
                busy,
                run_type="chat",
                capability="chat.completion",
                executor_type="chat",
                parameters={"model": "llamacpp:" + model_id, "endpoint": instance.endpoint},
            )
            with pytest.raises(ProviderError, match="active work"):
                prepare_consumer(session, proposal(session, model_id))


def test_pending_load_finishes_before_coding_stop(coding_fit):
    from app.llama import prepare_consumer
    from app.models import RunDependency

    model_id, _ = coding_fit
    with TestClient(app) as client:
        queued = load(client, model_id)
        with session_factory()() as session:
            run = proposal(session, model_id)
            prepare_consumer(session, run)
            session.commit()
            stop = session.scalar(select(Run).where(Run.executor_type == "llama_stop"))
            fresh = next(
                item
                for item in session.scalars(select(Run).where(Run.executor_type == "llama_load"))
                if item.id != queued["id"]
            )
            assert session.scalar(
                select(RunDependency).where(
                    RunDependency.run_id == stop.id, RunDependency.prerequisite_id == queued["id"]
                )
            )
            assert session.scalar(
                select(RunDependency).where(
                    RunDependency.run_id == fresh.id, RunDependency.prerequisite_id == stop.id
                )
            )


def test_already_large_q8_runtime_is_reused(coding_fit):
    from app.llama import prepare_consumer

    model_id, _ = coding_fit
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        with session_factory()() as session:
            instance = instances(session)[0]
            instance.metadata_json = {
                **instance.metadata_json,
                "context_size": two_12gb(),
                "cache_type": "q8_0",
            }
            session.commit()
            run = proposal(session, model_id)
            prepare_consumer(session, run)
            session.commit()
            assert run.parameters["endpoint"] == instance.endpoint
            assert len(list(session.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 1
            assert not list(session.scalars(select(Run).where(Run.executor_type == "llama_stop")))


def test_stopped_reload_uses_fitted_q8_not_saved_4096(coding_fit):
    from app.llama import prepare_consumer

    model_id, _ = coding_fit
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        client.post(f"/api/llama/{client.get('/api/llama').json()['instances'][0]['id']}/stop")
        tick_once()
        with session_factory()() as session:
            run = proposal(session, model_id)
            prepare_consumer(session, run)
            session.commit()
            fresh = next(
                item
                for item in session.scalars(select(Run).where(Run.executor_type == "llama_load"))
                if item.status == "queued"
            )
            assert fresh.parameters["context_size"] == two_12gb()
            assert fresh.parameters["cache_type"] == "q8_0"


def test_known_failed_context_is_not_retried(coding_fit):
    from app.llama import LoadModel, enqueue_load, fit_coding_context, prepare_consumer
    from app.models import RuntimeInstance

    model_id, _ = coding_fit
    fitted = two_12gb()
    with session_factory()() as session:
        failed = enqueue_load(
            LoadModel(model_file_id=model_id, gpus=[2, 7], context_size=131072, cache_type="q8_0"), session
        )
        instance = session.get(RuntimeInstance, failed.parameters["instance_id"])
        instance.status = "failed"
        instance.metadata_json = {**instance.metadata_json, "context_fit": "too_large"}
        session.commit()
        assert instance.metadata_json["context_size"] == fitted
        run = proposal(session, model_id)
        prepare_consumer(session, run)
        session.commit()
        fresh = next(
            item
            for item in session.scalars(select(Run).where(Run.executor_type == "llama_load"))
            if item.id != failed.id
        )
        expected = fit_coding_context(
            gpus=[2, 7], size_bytes=WEIGHTS_27B, gpu_memory_mib=[12288.0, 12288.0], failed_sizes=[fitted]
        )
        assert fresh.parameters["context_size"] == expected
        assert expected < fitted


def test_ready_runtime_persists_observed_n_ctx(coding_fit, monkeypatch):
    model_id, records = coding_fit
    fitted = two_12gb()

    def load_with_meta(_, body):
        records[body["instance_id"]] = {
            "status": "ready",
            "alive": True,
            "gpus": body["gpus"],
            "n_ctx": body["context_size"],
            "n_ctx_train": 262144,
        }
        return records[body["instance_id"]]

    monkeypatch.setattr(RunnerClient, "load_llama", load_with_meta)
    monkeypatch.setattr(RunnerClient, "inspect_llama", lambda _, identity: records[identity])
    with TestClient(app) as client:
        response = client.post(
            "/api/llama/load",
            json={"model_file_id": model_id, "gpus": [2, 7], "context_size": 131072, "cache_type": "q8_0"},
        )
        tick_once()
        instance = client.get("/api/llama").json()["instances"][0]
        assert instance["metadata"]["context_size"] == fitted
        assert instance["metadata"]["n_ctx_train"] == 262144
        assert instance["metadata"]["observation"]["n_ctx"] == fitted
        assert instance["metadata"]["observation"]["n_ctx_train"] == 262144
        events = client.get(f"/api/runs/{response.json()['id']}/events").json()
        ready = next(event for event in events if event["event_type"] == "runtime.ready")
        assert ready["payload"]["n_ctx"] == fitted
        assert ready["payload"]["n_ctx_train"] == 262144
        assert ready["payload"]["context_size"] == fitted


def test_health_inspects_owned_runtime_and_does_not_signal_externals(managed):
    model_id, records = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        instance = client.get("/api/llama").json()["instances"][0]
        records[instance["id"]] = {
            **records[instance["id"]],
            "status": "ready",
            "alive": True,
            "n_ctx": 4096,
            "pid": 4242,
        }
        response = client.post(f"/api/llama/{instance['id']}/health", json={})
        assert response.status_code == 202, response.text
        tick_once()
        run = client.get("/api/runs/" + response.json()["id"]).json()
        assert run["status"] == "succeeded"
        assert "External runtimes were not signalled" in run["summary"]
        assert client.get("/api/artifacts?run_id=" + run["id"]).json()[0]["type"] == "json"
        stored = client.get("/api/llama").json()["instances"][0]
        assert stored["metadata"]["health"]["alive"] is True
        assert stored["metadata"]["health"]["n_ctx"] == 4096
        assert client.post(f"/api/llama/{instance['id']}/health", json={"signal": 9}).status_code == 422


def test_health_records_a_dead_owned_container_without_claiming_it_healthy(managed, monkeypatch):
    model_id, _records = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        instance = client.get("/api/llama").json()["instances"][0]

        def missing(_self, _identity):
            from app.runner_client import RunnerError

            raise RunnerError(404, "gone")

        monkeypatch.setattr(RunnerClient, "inspect_llama", missing)
        run = client.post(f"/api/llama/{instance['id']}/health", json={}).json()
        tick_once()
        body = client.get("/api/runs/" + run["id"]).json()
        assert body["status"] == "succeeded"
        stored = client.get("/api/llama").json()["instances"][0]
        assert stored["status"] == "stopped"
        assert stored["metadata"]["health"]["alive"] is False


def test_restart_stops_then_reloads_saved_preset_and_rejects_busy_or_external(managed, monkeypatch):
    from app.models import RuntimeInstance

    model_id, records = managed
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        instance = client.get("/api/llama").json()["instances"][0]
        restart = client.post(f"/api/llama/{instance['id']}/restart", json={})
        assert restart.status_code == 202, restart.text
        tick_once()
        tick_once()
        load_id = restart.json()["id"]
        with session_factory()() as session:
            load_run = session.get(Run, load_id)
            assert load_run.executor_type == "llama_load"
            assert load_run.status == "succeeded"
        deps = client.get(f"/api/runs/{load_id}/events").json()
        assert any(event["event_type"] == "runtime.restart_requested" for event in deps)
        catalog = client.get("/api/llama").json()["instances"]
        assert any(item["status"] == "ready" and item["id"] != instance["id"] for item in catalog)
        with session_factory()() as session:
            foreign = RuntimeInstance(
                runtime_key="llama.cpp", name="external", ownership="external", status="observed"
            )
            session.add(foreign)
            session.commit()
            foreign_id = foreign.id
        assert client.post(f"/api/llama/{foreign_id}/health", json={}).status_code == 404
        assert client.post(f"/api/llama/{foreign_id}/restart", json={}).status_code == 404
        ready = next(
            item for item in client.get("/api/llama").json()["instances"] if item["status"] == "ready"
        )
        conv = client.post("/api/chat/conversations", json={"model": "llamacpp:" + model_id}).json()
        client.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"})
        assert client.post(f"/api/llama/{ready['id']}/restart", json={}).status_code == 409


def hybrid_profile():
    return {
        "source": "gguf_header",
        "architecture": "qwen35",
        "trained_context": 262144,
        "attention_layers": 16,
        "q8_kv_bytes_per_token": 34816,
        "state_reserve_mib": 512,
    }


def test_architecture_estimate_is_independent_of_weight_quantization():
    from app.llama import fit_coding_context

    common = dict(gpus=[2, 7], gpu_memory_mib=[12288, 12288], context_profile=hybrid_profile())
    assert fit_coding_context(size_bytes=9090591264, **common) == 131072
    fitted = fit_coding_context(size_bytes=16547400224, **common)
    assert 81920 <= fitted < 131072
    limited = fit_coding_context(
        size_bytes=9090591264, **{**common, "context_profile": {**hybrid_profile(), "trained_context": 32768}}
    )
    assert limited == 32768
    assert (
        fit_coding_context(
            size_bytes=9090591264,
            **{**common, "context_profile": {**hybrid_profile(), "trained_context": 2048}},
        )
        == 2048
    )


def test_worker_inspects_before_loading_and_records_immutable_profile(coding_fit, monkeypatch):
    model_id, records = coding_fit
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {
            "gpus": [{"index": 2, "memory_total_mib": 12288}, {"index": 7, "memory_total_mib": 12288}]
        },
    )
    inspected = []
    dispatched = []

    def verify(_, body):
        inspected.append(body)
        return {"present": True, "matches_observation": True, "context_profile": hybrid_profile()}

    monkeypatch.setattr(RunnerClient, "verify_model", verify)
    original = RunnerClient.load_llama

    def load_record(client, body):
        dispatched.append(body)
        return original(client, body)

    monkeypatch.setattr(RunnerClient, "load_llama", load_record)
    with TestClient(app) as client:
        response = client.post(
            "/api/llama/load",
            json={"model_file_id": model_id, "gpus": [2, 7], "context_size": 131072, "cache_type": "q8_0"},
        )
        assert response.status_code == 202
        assert inspected == [] and dispatched == []
        queued = response.json()
        tick_once()
        assert len(inspected) == len(dispatched) == 1
        assert inspected[0]["run_id"] == queued["id"]
        assert dispatched[0]["context_size"] > queued["parameters"]["context_size"]
        with session_factory()() as session:
            run = session.get(Run, queued["id"])
            runtime = instances(session)[0]
            assert run.status == "succeeded"
            assert run.parameters["requested_context_size"] == 131072
            assert runtime.metadata_json["context_profile"] == hybrid_profile()
            from app.llama import coding_context_target

            assert (
                coding_context_target(session, session.get(ModelFile, model_id), [2, 7])
                == dispatched[0]["context_size"]
            )


def test_cancellation_during_header_inspection_never_dispatches(coding_fit, monkeypatch):
    model_id, records = coding_fit

    def verify(_, body):
        with session_factory()() as session:
            request_cancel(session, session.get(Run, body["run_id"]))
            session.commit()
        return {"present": True, "matches_observation": True, "context_profile": hybrid_profile()}

    monkeypatch.setattr(RunnerClient, "verify_model", verify)
    with TestClient(app) as client:
        queued = client.post(
            "/api/llama/load",
            json={"model_file_id": model_id, "gpus": [2, 7], "context_size": 131072, "cache_type": "q8_0"},
        ).json()
        tick_once()
        with session_factory()() as session:
            assert session.get(Run, queued["id"]).status == "canceled"
            assert not active_locks(session)
        assert records == {}


def test_changed_file_fails_before_dispatch_and_does_not_block_future_loads(coding_fit, monkeypatch):
    model_id, records = coding_fit
    monkeypatch.setattr(
        RunnerClient, "verify_model", lambda _, body: {"present": True, "matches_observation": False}
    )
    with TestClient(app) as client:
        body = {"model_file_id": model_id, "gpus": [2, 7], "context_size": 131072, "cache_type": "q8_0"}
        queued = client.post("/api/llama/load", json=body).json()
        tick_once()
        with session_factory()() as session:
            assert session.get(Run, queued["id"]).status == "failed"
            assert instances(session)[0].status == "failed"
            assert not active_locks(session)
        assert records == {}
        assert client.post("/api/llama/load", json=body).status_code == 202


def test_new_header_estimate_cannot_exceed_a_previously_failed_allocation():
    from app.llama import fit_coding_context

    fitted = fit_coding_context(
        gpus=[0, 1],
        size_bytes=9090591264,
        gpu_memory_mib=[12288, 12288],
        context_profile=hybrid_profile(),
        failed_sizes=[65536],
    )
    assert fitted <= 32768
