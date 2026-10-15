import io
from uuid import uuid4

import pytest
from app.api import app
from app.conversation_media import followup_action
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Run
from app.runs import transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select


def completed_image(client, cid):
    response = client.post(
        f"/api/chat/conversations/{cid}/messages", json={"content": "Generate an image of a landscape"}
    )
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        tick(session, "test-media-followup")
        producer = session.scalar(select(Run).where(Run.parent_run_id == response.json()["id"]))
        for status in [RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.SUCCEEDED]:
            transition(session, producer, status, event_type="test.transition")
        session.commit()
        producer_id = producer.id
    data = io.BytesIO()
    Image.new("RGB", (64, 64)).save(data, "PNG")
    uploaded = client.post(
        "/api/images/uploads", files={"file": ("result.png", data.getvalue(), "image/png")}
    ).json()
    with session_factory()() as session:
        session.get(Artifact, uploaded["id"]).run_id = producer_id
        session.commit()
    return uploaded["id"], producer_id


def conversation(client, mode="work"):
    r = client.post("/api/chat/conversations", json={"model": "test", "execution_mode": mode})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize(
    ("content", "action"),
    [
        ("Powiększ to", "image.upscale"),
        ("Upscale the previous image.", "image.upscale"),
        ("Ożyw ten obraz: spokojny ruch kamery", "video.generate"),
        ("Animate it into a 5 second video", "video.generate"),
        ("Zmień ten obraz: dodaj kapelusz", "image.edit"),
        ("Edit this image: add a red hat", "image.edit"),
    ],
)
def test_followup_is_bound_to_visible_same_conversation_result(content, action):
    with TestClient(app) as client:
        cid = conversation(client)
        aid, producer = completed_image(client, cid)
        completed_image(client, conversation(client))
        request = {
            "content": content,
            "client_request_id": str(uuid4()),
            "conversation_id": cid,
            "expected_settings_version": 1,
        }
        response = client.post("/api/chat/turns", json=request)
        assert response.status_code == 202, response.text
        run = response.json()["run"]
        assert run["parameters"]["action"] == action
        assert run["parameters"]["image_artifact_ids"] == [aid]
        assert "external_ai" not in run["effective_permissions"]
        view = client.get(f"/api/chat/conversations/{cid}").json()
        user = next(m for m in view["messages"] if m["id"] == response.json()["user_message_id"])
        assert user["metadata"]["conversation_reference"]["run_id"] == producer
        assert user["metadata"]["images"][0]["id"] == aid
        assert client.post("/api/chat/turns", json=request).json()["run"]["id"] == run["id"]


@pytest.mark.parametrize("problem", ["trashed", "failed", "ambiguous"])
def test_unavailable_or_ambiguous_latest_result_never_falls_back(problem):
    with TestClient(app) as client:
        cid = conversation(client)
        completed_image(client, cid)
        aid, producer = completed_image(client, cid)
        with session_factory()() as session:
            if problem == "trashed":
                session.get(Artifact, aid).trashed_at = utcnow()
            elif problem == "failed":
                session.get(Run, producer).status = "failed"
            else:
                a = session.get(Artifact, aid)
                session.add(
                    Artifact(
                        artifact_type="image",
                        mime_type="image/png",
                        relative_path=a.relative_path,
                        run_id=producer,
                    )
                )
            before = len(list(session.scalars(select(Run))))
            session.commit()
        r = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Upscale it"})
        assert r.status_code == 422, r.text
        with session_factory()() as session:
            assert len(list(session.scalars(select(Run)))) == before


def test_only_final_derived_image_is_selected_and_chat_uses_same_contract():
    with TestClient(app) as client:
        cid = conversation(client, "chat")
        aid, producer = completed_image(client, cid)
        with session_factory()() as session:
            a = session.get(Artifact, aid)
            derived = Artifact(
                artifact_type="image",
                mime_type="image/png",
                relative_path=a.relative_path,
                run_id=producer,
                parent_artifact_ids=[aid],
                metadata_json=a.metadata_json,
            )
            session.add(derived)
            session.flush()
            final = derived.id
            session.commit()
        r = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Powiększ to"})
        assert r.status_code == 202, r.text
        assert r.json()["parameters"]["image_artifact_ids"] == [final]
        with session_factory()() as session:
            tick(session, "test-media-followup")
            child = session.scalar(select(Run).where(Run.parent_run_id == r.json()["id"]))
            assert child.parameters["mode"] == "upscale"
            assert child.parameters["parent_artifact_ids"] == [final]


def test_explicit_sources_are_never_replaced():
    with TestClient(app) as client:
        cid = conversation(client)
        old, _ = completed_image(client, cid)
        completed_image(client, cid)
        r = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Powiększ to", "image_artifact_ids": [old], "action": "image.upscale"},
        )
        assert r.status_code == 202
        assert r.json()["parameters"]["image_artifact_ids"] == [old]


def test_missing_result_rejects_without_creating_messages_or_receipts():
    with TestClient(app) as client:
        cid = conversation(client)
        r = client.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "conversation_id": cid,
                "expected_settings_version": 1,
                "content": "Upscale it",
            },
        )
        assert r.status_code == 422
        assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []


@pytest.mark.parametrize(
    "text",
    [
        "Explain how to upscale this image",
        "Do not upscale it",
        "Can we discuss this image?",
        "Change this project: add login",
        "Animate my project",
        "Generate an image",
        "Upscale",
        "Edit this image",
    ],
)
def test_noncommands_never_acquire_previous_sources(text):
    assert followup_action(text) is None
