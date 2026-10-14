import asyncio
from uuid import uuid4

import pytest
from app.api import app
from app.chat_reasoning import CompletionFinished, ReasoningDelta, certificate
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, ModelDefinition, ModelFile, Run, RuntimeInstance
from app.runner_client import RunnerClient
from app.runs import create_run, create_task, request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["plain"])
    with session_factory()() as session:
        file = ModelFile(
            host_path="/configured/thinking.gguf",
            filename="thinking.gguf",
            category="llm",
            format="gguf",
            availability="present",
            size_bytes=123,
            mtime=456,
        )
        session.add(file)
        session.flush()
        task = create_task(session, title="Fixture load", prompt="", capability="runtime.load")
        load = create_run(
            session, task, run_type="model", capability="runtime.load", executor_type="llama_load"
        )
        load.status = "succeeded"
        instance = RuntimeInstance(
            id=str(uuid4()),
            runtime_key="llama.cpp",
            ownership="managed",
            name="Fixture",
            status="ready",
            metadata_json={
                "model_file_id": file.id,
                "load_run_id": load.id,
                "gpus": [2, 7],
                "context_size": 4096,
            },
        )
        instance.endpoint = "llamacpp:" + instance.id
        session.add(instance)
        session.commit()
        result = {"id": file.id, "model": "llamacpp:" + file.id, "instance": instance.id}
    monkeypatch.setattr(
        RunnerClient,
        "request",
        lambda *a, **k: {"status": "ready", "image_id": "sha256:" + "a" * 64, "template_sha256": "b" * 64},
    )

    async def stream(self, **params):
        if params.get("reasoning", {}).get("enabled"):
            yield ReasoningDelta("Compute using partial products.")
        yield "391"
        if params.get("reasoning") is not None:
            yield CompletionFinished("stop")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return result


def qualify(client, model):
    response = client.post("/api/llama/models/" + model["id"] + "/reasoning-check")
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        tick(session, "probe")
    run = client.get("/api/runs/" + response.json()["id"]).json()
    assert run["status"] == "succeeded", run
    return run


def test_qualification_enables_bound_chat_and_keeps_thinking_out_of_final_content(model):
    with TestClient(app) as client:
        denied = client.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "selection": {"model": model["model"], "execution_mode": "chat"},
                "content": "Explain",
                "reasoning": {"enabled": True},
            },
        )
        assert denied.status_code == 422
        run = qualify(client, model)
        assert run["metadata"]["reasoning_qualification"]["probes"][0]["thinking_characters"] == 0
        with session_factory()() as session:
            assert certificate(session, model["model"])["source_run_id"] == run["id"]
            assert session.scalar(select(Artifact).where(Artifact.run_id == run["id"])) is not None
        catalog = client.get("/api/chat/model-catalog").json()
        assert next(m for m in catalog["models"] if m["model_key"] == model["model"])["reasoning_capability"][
            "verified"
        ]
        response = client.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "selection": {"model": model["model"], "execution_mode": "chat"},
                "content": "Explain",
                "reasoning": {"enabled": True},
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "chat")
        detail = client.get("/api/chat/conversations/" + response.json()["conversation_id"]).json()
        answer = detail["messages"][-1]
        assert (
            answer["content"] == "391"
            and answer["metadata"]["reasoning_text"] == "Compute using partial products."
        )
        assert answer["run_status"] == "succeeded"


def test_qualification_cancellation_closes_stream_without_enabling_capability(model, monkeypatch):
    closed = []
    with TestClient(app) as client:
        run = client.post("/api/llama/models/" + model["id"] + "/reasoning-check").json()

        async def blocked(self, **params):
            try:
                with session_factory()() as session:
                    request_cancel(session, session.get(Run, run["id"]))
                    session.commit()
                await asyncio.sleep(30)
                yield "late"
            finally:
                closed.append(True)

        monkeypatch.setattr(LocalChatProvider, "stream", blocked)
        with session_factory()() as session:
            tick(session, "cancel-probe")
        assert client.get("/api/runs/" + run["id"]).json()["status"] == "canceled"
        assert closed
        with session_factory()() as session:
            assert certificate(session, model["model"]) is None


def test_unqualified_empty_thinking_and_stale_model_do_not_advertise_support(model, monkeypatch):
    async def plain(self, **params):
        yield "391"

    monkeypatch.setattr(LocalChatProvider, "stream", plain)
    with TestClient(app) as client:
        run = client.post("/api/llama/models/" + model["id"] + "/reasoning-check").json()
        with session_factory()() as session:
            tick(session, "unsupported")
        assert client.get("/api/runs/" + run["id"]).json()["status"] == "failed"
        with session_factory()() as session:
            assert certificate(session, model["model"]) is None


def test_output_limit_preserves_partial_answer_and_runtime_identity_changes_fail_closed(model, monkeypatch):
    with TestClient(app) as client:
        qualify(client, model)

        async def truncated(self, **params):
            yield ReasoningDelta("Work in progress")
            yield "Partial answer"
            yield CompletionFinished("length")

        monkeypatch.setattr(LocalChatProvider, "stream", truncated)
        body = {
            "client_request_id": str(uuid4()),
            "selection": {"model": model["model"], "execution_mode": "chat"},
            "content": "Explain",
            "reasoning": {"enabled": True},
        }
        response = client.post("/api/chat/turns", json=body)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "limit")
        run = client.get("/api/runs/" + response.json()["run"]["id"]).json()
        assert run["status"] == "failed" and "budget exhausted" in run["error_message"]
        message = client.get("/api/chat/conversations/" + response.json()["conversation_id"]).json()[
            "messages"
        ][-1]
        assert (
            message["content"] == "Partial answer"
            and message["metadata"]["reasoning_text"] == "Work in progress"
        )
        monkeypatch.setattr(
            RunnerClient,
            "request",
            lambda *a, **k: {
                "status": "ready",
                "image_id": "sha256:" + "c" * 64,
                "template_sha256": "b" * 64,
            },
        )
        body["client_request_id"] = str(uuid4())
        second = client.post("/api/chat/turns", json=body)
        with session_factory()() as session:
            tick(session, "changed-runtime")
        assert client.get("/api/runs/" + second.json()["run"]["id"]).json()["status"] == "failed"


def test_changed_file_and_stale_lease_never_publish_qualified_capability(model):
    from datetime import timedelta

    from app.db import utcnow
    from app.recovery import recover_stale

    with TestClient(app) as client:
        qualify(client, model)
        with session_factory()() as session:
            session.get(ModelFile, model["id"]).mtime = 789
            session.commit()
            assert certificate(session, model["model"]) is None
        run = client.post("/api/llama/models/" + model["id"] + "/reasoning-check").json()

        class Gone:
            def inspect_process(self, run_id):
                return {"alive": False}

        with session_factory()() as session:
            lost = session.get(Run, run["id"])
            lost.status = "running"
            lost.lease_expires_at = utcnow() - timedelta(seconds=60)
            session.commit()
            recover_stale(session, Gone())
            session.commit()
            assert session.get(Run, run["id"]).status == "interrupted"
            assert certificate(session, model["model"]) is None


def test_repeated_check_reuses_pending_run_and_modified_metadata_is_not_proof(model):
    with TestClient(app) as client:
        first = client.post("/api/llama/models/" + model["id"] + "/reasoning-check").json()
        assert (
            client.post("/api/llama/models/" + model["id"] + "/reasoning-check").json()["id"] == first["id"]
        )
        with session_factory()() as session:
            tick(session, "proof")
            assert certificate(session, model["model"])
            definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == model["id"]))
            qualification = {**definition.metadata_json["reasoning_qualification"], "image_id": "forged"}
            definition.metadata_json = {**definition.metadata_json, "reasoning_qualification": qualification}
            session.commit()
            assert certificate(session, model["model"]) is None
