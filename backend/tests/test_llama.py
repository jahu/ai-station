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
