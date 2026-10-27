"""Ordinary visual questions inspect the exact result; passive Web is not research authority."""

import io
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Artifact, Message, Run
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from test_media_translation import fake as fake  # noqa: F401
from test_media_translation import work
from test_stopped_media_retry import stopped_media
from test_vision import vision_runtime as vision_runtime  # noqa: F401


@pytest.mark.parametrize("mode", ["assistant", "chat", "work"])
def test_question_after_stopped_retry_uses_exact_pixels_without_web_or_regeneration(
    fake, vision_runtime, monkeypatch, mode
):
    seen = []

    async def stream(self, **params):
        seen.append(params)
        yield "A red rectangle."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        source, old_task, cid = stopped_media(client)
        retry = client.post(f"/api/images/runs/{source}/retry", json={"translation": "original"})
        assert retry.status_code == 202, retry.text
        rid = retry.json()["id"]
        work()
        data = io.BytesIO()
        Image.new("RGB", (80, 40), "red").save(data, "PNG")
        image = client.post(
            "/api/images/uploads", files={"file": ("result.png", data.getvalue(), "image/png")}
        ).json()
        with session_factory()() as session:
            session.get(Artifact, image["id"]).run_id = rid
            session.commit()
        request = {
            "conversation_id": cid,
            "client_request_id": str(uuid4()),
            "expected_settings_version": 1,
            "execution_mode": mode,
            "content": "Co znajduje się na wygenerowanym zdjęciu? Nie twórz kolejnego obrazu.",
            "web_search": {"enabled": True},
        }
        response = client.post("/api/chat/turns", json=request)
        assert response.status_code == 202, response.text
        parent = response.json()["run"]
        assert parent["parameters"]["action"] == "image.describe"
        assert parent["parameters"]["image_artifact_ids"] == [image["id"]]
        assert not parent["parameters"]["web_search"]["enabled"]
        assert parent["task_id"] not in {old_task, retry.json()["task_id"]}
        assert client.post("/api/chat/turns", json=request).json()["run"]["id"] == parent["id"]
        for _ in range(6):
            work()
        with session_factory()() as session:
            root = session.get(Run, parent["id"])
            child = session.scalar(
                select(Run).where(Run.parent_run_id == root.id, Run.capability == "chat.vision")
            )
            assert root.status == child.status == "succeeded", root.error_message
            assert child.parameters["vision_artifact_ids"] == [image["id"]]
            assert child.parameters["vision_inputs"][0]["sha256"] == image["sha256"]
            assert child.parameters["location"] == "local"
            assert len(fake[1]) == 1  # Only the original retry generated an image.
            assert session.get(Run, source).status == "canceled"
            answer = session.scalar(
                select(Message).where(Message.run_id == child.id, Message.role == "assistant")
            )
            assert answer.content == "A red rectangle."
            assert not answer.metadata_json.get("web_search", {}).get("sources")
        assert len(seen) == 1
        parts = seen[0]["messages"][0]["content"]
        assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
