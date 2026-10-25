import asyncio
import io
import json

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, ModelFile, Run, TelemetrySample
from app.runner_client import RunnerClient
from app.runs import request_cancel
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select


@pytest.fixture
def vision_runtime(monkeypatch):
    records = {}
    requests = []
    with session_factory()() as session:
        model = ModelFile(
            host_path="/models/vision/model.gguf",
            filename="model.gguf",
            format="gguf",
            category="llm",
            availability="present",
            size_bytes=1000,
            mtime=1,
        )
        projector = ModelFile(
            host_path="/models/vision/mmproj.gguf",
            filename="mmproj.gguf",
            format="gguf",
            category="llm",
            availability="present",
            size_bytes=500,
            mtime=1,
        )
        session.add_all(
            [model, projector, TelemetrySample(payload={"gpus": [{"index": 7}]}, sampled_at=utcnow())]
        )
        session.commit()
        model_id = model.id
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"gpus": [{"index": 7}]})

    def load(_, body):
        requests.append(body)
        records[body["instance_id"]] = {"status": "ready", "alive": True, "gpus": body["gpus"]}
        return records[body["instance_id"]]

    monkeypatch.setattr(RunnerClient, "load_llama", load)
    monkeypatch.setattr(RunnerClient, "inspect_llama", lambda _, id: records[id])
    monkeypatch.setattr(RunnerClient, "stop_llama", lambda _, id: {"status": "stopped", "alive": False})
    return model_id, requests


def step():
    with session_factory()() as session:
        return tick(session, "vision-test")


def setup(client):
    conversation = client.post(
        "/api/chat/conversations", json={"model": "unavailable-text-model", "execution_mode": "orchestrator"}
    ).json()
    output = io.BytesIO()
    Image.new("RGB", (80, 40), "red").save(output, "PNG")
    image = client.post(
        "/api/images/uploads", files={"file": ("red.png", output.getvalue(), "image/png")}
    ).json()
    return conversation["id"], image["id"]


def test_pixels_stream_from_worker_with_local_model_and_parent_artifact(vision_runtime, monkeypatch):
    model_id, requests = vision_runtime
    seen = []

    async def stream(self, **params):
        seen.append(params)
        yield "A red rectangle."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        conversation, image = setup(client)
        route = f"/api/chat/conversations/{conversation}/messages"
        response = client.post(route, json={"content": "Opisz obraz", "image_artifact_ids": [image]})
        assert response.status_code == 202, response.text
        assert not requests and not seen
        assert len(client.get("/api/llama").json()["models"]) == 1
        assert client.get("/api/llama").json()["models"][0]["vision_available"] is True
        step()
        step()
        step()
        assert len(requests) == len(seen) == 1
        assert requests[0]["projector"]["path"] == "/models/vision/mmproj.gguf"
        assert requests[0]["gpus"] == [7]
        assert seen[0]["location"] == "local"
        assert seen[0]["model"] == "llamacpp:" + model_id
        parts = seen[0]["messages"][0]["content"]
        assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        detail = client.get("/api/chat/conversations/" + conversation).json()
        assert detail["messages"][-1]["content"] == "A red rectangle."
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.capability == "chat.vision"))
            assert run.status == "succeeded"
            assert run.parent_run_id == response.json()["id"]
            assert "base64" not in json.dumps(run.parameters)
            artifact = session.scalar(select(Artifact).where(Artifact.run_id == run.id))
            assert artifact.parent_artifact_ids == [image]
            assert artifact.artifact_type == "markdown"
            assert artifact.metadata_json["location"] == "local"


def test_explicit_vision_rejects_missing_images_without_running(vision_runtime):
    _, requests = vision_runtime
    with TestClient(app) as client:
        conversation, _ = setup(client)
        response = client.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={"content": "Inspect", "action": "image.describe"},
        )
        assert response.status_code == 422
        assert not requests
        assert client.get("/api/chat/conversations/" + conversation).json()["messages"] == []


def test_permission_denial_cannot_load_vision_model(vision_runtime):
    _, requests = vision_runtime
    with TestClient(app) as client:
        conversation, image = setup(client)
        response = client.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={"content": "Describe", "action": "image.describe", "image_artifact_ids": [image]},
        )
        with session_factory()() as session:
            session.get(Run, response.json()["id"]).effective_permissions = []
            session.commit()
        step()
        assert not requests
        with session_factory()() as session:
            assert session.get(Run, response.json()["id"]).status == "failed"
            assert not session.scalar(select(Run.id).where(Run.executor_type == "llama_load"))


def test_image_path_escape_fails_before_model_request(vision_runtime, monkeypatch):
    _, requests = vision_runtime
    seen = []

    async def stream(self, **params):
        seen.append(params)
        yield "unexpected"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        conversation, image = setup(client)
        client.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={"content": "Inspect image", "action": "image.describe", "image_artifact_ids": [image]},
        )
        step()
        step()
        with session_factory()() as session:
            session.get(Artifact, image).relative_path = "../outside.png"
            session.commit()
        step()
        assert not seen
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.capability == "chat.vision"))
            assert run.status == "failed"
            assert not session.scalar(select(Artifact.id).where(Artifact.run_id == run.id))


def test_vision_cancellation_closes_stream_without_description_artifact(vision_runtime, monkeypatch):
    closed = []

    async def stream(self, **params):
        try:
            with session_factory()() as session:
                run = session.scalar(select(Run).where(Run.capability == "chat.vision"))
                request_cancel(session, run)
                session.commit()
            await asyncio.sleep(0.4)
            yield "never complete"
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        conversation, image = setup(client)
        client.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={"content": "Inspect image", "action": "image.describe", "image_artifact_ids": [image]},
        )
        step()
        step()
        step()
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.capability == "chat.vision"))
            assert run.status == "canceled"
            assert not session.scalar(select(Artifact.id).where(Artifact.run_id == run.id))
        assert closed == [True]


def test_no_installed_companion_reports_unavailable(vision_runtime):
    with session_factory()() as session:
        projector = session.scalar(select(ModelFile).where(ModelFile.filename == "mmproj.gguf"))
        projector.availability = "missing"
        session.commit()
    with TestClient(app) as client:
        conversation, image = setup(client)
        client.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={"content": "Inspect image", "action": "image.describe", "image_artifact_ids": [image]},
        )
        step()
        assert (
            "Scan your installed vision GGUF"
            in client.get("/api/chat/conversations/" + conversation).json()["messages"][-1]["content"]
        )


def test_rejected_provider_does_not_leave_model_load_or_unload_children(vision_runtime, monkeypatch):
    from fastapi import HTTPException

    def unavailable(*args):
        raise HTTPException(409, "Local model configuration is unavailable")

    monkeypatch.setattr("app.vision.snapshot_provider", unavailable)
    with TestClient(app) as client:
        conversation, image = setup(client)
        response = client.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={"content": "Inspect image", "action": "image.describe", "image_artifact_ids": [image]},
        )
        assert response.status_code == 202, response.text
        step()
        with session_factory()() as session:
            assert not session.scalar(
                select(Run.id).where(Run.executor_type.in_(["llama_load", "llama_stop"]))
            )


def test_transparency_is_composited_without_revealing_hidden_pixels(vision_runtime):
    import base64

    from app.vision import inline_image

    with TestClient(app) as client:
        output = io.BytesIO()
        Image.new("RGBA", (16, 16), (255, 0, 0, 0)).save(output, "PNG")
        uploaded = client.post(
            "/api/images/uploads", files={"file": ("transparent.png", output.getvalue(), "image/png")}
        ).json()
        with session_factory()() as session:
            part = inline_image(session.get(Artifact, uploaded["id"]))
        data = base64.b64decode(part["image_url"]["url"].partition(",")[2])
        with Image.open(io.BytesIO(data)) as decoded:
            assert all(channel > 240 for channel in decoded.getpixel((8, 8)))


def test_oversized_source_is_rejected_without_loading_a_model(vision_runtime):
    with TestClient(app) as client:
        conversation, image = setup(client)
        with session_factory()() as session:
            session.get(Artifact, image).size_bytes = 21 * 1024 * 1024
            session.commit()
        response = client.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={"content": "Inspect image", "action": "image.describe", "image_artifact_ids": [image]},
        )
        assert response.status_code == 202, response.text
        step()
        with session_factory()() as session:
            assert not session.scalar(select(Run.id).where(Run.executor_type == "llama_load"))


@pytest.mark.parametrize("action", ["auto", "chat"])
@pytest.mark.parametrize("mode", ["chat", "assistant"])
@pytest.mark.parametrize(
    "prompt",
    ["Jaki kolor ma ten prostokąt?", "Czy widzisz czerwony kształt?", "How many shapes are visible?"],
)
def test_chat_image_questions_use_only_vision_without_a_text_provider_or_prerequisite(
    vision_runtime, monkeypatch, action, prompt, mode
):
    from app import assistant, chat, llama

    model_id, loads = vision_runtime
    seen = []

    async def stream(self, **params):
        seen.append(params)
        yield "A red rectangle."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        cid, image = setup(client)

        def unexpected(*args, **kwargs):
            raise AssertionError("A selected-image Chat question must not prepare its text provider")

        monkeypatch.setattr(assistant, "snapshot_provider", unexpected)
        monkeypatch.setattr(chat, "snapshot_provider", unexpected)
        monkeypatch.setattr(llama, "prepare_consumer", unexpected)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": prompt,
                "image_artifact_ids": [image],
                "execution_mode": mode,
                "action": action,
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            root = session.get(Run, response.json()["id"])
            assert "endpoint" not in root.parameters and "external_ai" not in root.effective_permissions
            assert not list(session.scalars(select(Run).where(Run.executor_type == "llama_load")))
        for _ in range(3):
            assert step()
        assert len(loads) == len(seen) == 1
        assert seen[0]["location"] == "local" and seen[0]["model"] == "llamacpp:" + model_id
        answer = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert answer["content"] == "A red rectangle."
        with session_factory()() as session:
            result = session.scalar(select(Run).where(Run.capability == "chat.vision"))
            artifact = session.scalar(select(Artifact).where(Artifact.run_id == result.id))
            assert artifact.parent_artifact_ids == [image]
            assert result.task_id == response.json()["task_id"] and result.status == "succeeded"
