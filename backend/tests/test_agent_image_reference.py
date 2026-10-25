"""Agent image outputs reuse ordinary typed image follow-up execution."""

import io

import pytest
from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import Artifact, Message, Run
from app.paths import safe_join
from PIL import Image
from test_agent_result_families import family_result
from test_conversation_agent_control import saved as saved
from test_conversation_agent_control import step
from test_conversation_media import completed_image


@pytest.fixture
def image_result(saved, monkeypatch):
    completed_image(saved[0], saved[1])
    mid, rid, old = family_result(saved, monkeypatch, "media")
    data = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(data, "PNG")
    response = saved[0].post(
        "/api/images/uploads", files={"file": ("agent.png", data.getvalue(), "image/png")}
    )
    assert response.status_code == 201, response.text
    aid = response.json()["id"]
    with session_factory()() as db:
        previous = db.get(Artifact, old)
        previous.run_id = None
        previous.trashed_at = utcnow()
        db.get(Artifact, aid).run_id = rid
        db.commit()
    return mid, rid, aid


@pytest.mark.parametrize("mode", ["chat", "work"])
@pytest.mark.parametrize(
    "prompt,action",
    [
        ("Powiększ ten obraz", "image.upscale"),
        ("Zmień ten obraz: dodaj kapelusz", "image.edit"),
        ("Opisz ten obraz", "image.describe"),
        ("Describe it", "image.describe"),
        ("Ożyw ten obraz: spokojny ruch kamery", "video.generate"),
    ],
)
def test_explicit_agent_image_followup_selects_its_exact_published_source(
    saved, image_result, mode, prompt, action
):
    mid, rid, aid = image_result
    response = saved[0].post(
        f"/api/chat/conversations/{saved[1]}/messages", json={"content": prompt, "execution_mode": mode}
    )
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["parameters"]["image_artifact_ids"] == [aid]
    assert queued["parameters"]["action"] == action
    with session_factory()() as db:
        user = db.get(Message, queued["parameters"]["user_message_id"])
        ref = user.metadata_json["conversation_reference"]
        assert (
            ref["source_kind"] == "agent_image_result" and ref["message_id"] == mid and ref["run_id"] == rid
        )
        assert ref["artifact_id"] == aid


@pytest.mark.parametrize(
    "problem",
    [
        "trashed",
        "pending",
        "failed",
        "ambiguous",
        "link",
        "owner",
        "conversation",
        "bytes",
        "partial",
        "message_partial",
    ],
)
def test_unavailable_latest_agent_image_does_not_choose_an_older_image(saved, image_result, problem):
    mid, rid, aid = image_result
    with session_factory()() as db:
        producer = db.get(Run, rid)
        root = db.get(Run, producer.parent_run_id)
        artifact = db.get(Artifact, aid)
        if problem == "partial":
            artifact.metadata_json = {**artifact.metadata_json, "partial": True}
        elif problem == "message_partial":
            response = db.get(Message, mid)
            response.metadata_json = {**response.metadata_json, "partial": True}
        elif problem == "bytes":
            safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed PNG bytes")
        elif problem == "owner":
            producer.agent_id = None
        elif problem == "conversation":
            root.task.metadata_json = {**root.task.metadata_json, "originating_conversation_id": "another"}
        elif problem == "trashed":
            artifact.trashed_at = utcnow()
        elif problem == "pending":
            producer.status = "queued"
        elif problem == "failed":
            producer.status = "failed"
        elif problem == "link":
            root.task.metadata_json = {**root.task.metadata_json, "conversation_control_run_id": "wrong"}
        else:
            db.add(
                Artifact(
                    artifact_type="image",
                    mime_type=artifact.mime_type,
                    relative_path=artifact.relative_path,
                    size_bytes=artifact.size_bytes,
                    sha256=artifact.sha256,
                    run_id=rid,
                    metadata_json=artifact.metadata_json,
                )
            )
        db.commit()
    before = len(saved[0].get(f"/api/chat/conversations/{saved[1]}").json()["messages"])
    response = saved[0].post(
        f"/api/chat/conversations/{saved[1]}/messages", json={"content": "Powiększ ten obraz"}
    )
    assert response.status_code == 422, response.text
    assert len(saved[0].get(f"/api/chat/conversations/{saved[1]}").json()["messages"]) == before


def test_explicit_selected_image_keeps_precedence_over_the_agent_result(saved, image_result):
    _, _, aid = image_result
    response = saved[0].post(
        f"/api/chat/conversations/{saved[1]}/messages",
        json={"content": "Powiększ ten obraz", "image_artifact_ids": [aid]},
    )
    assert response.status_code == 202, response.text
    with session_factory()() as db:
        user = db.get(Message, response.json()["parameters"]["user_message_id"])
        assert "conversation_reference" not in user.metadata_json


def test_generic_text_followup_does_not_inspect_an_older_agent_image(saved, image_result):
    response = saved[0].post(
        f"/api/chat/conversations/{saved[1]}/messages",
        json={"content": "Explain a different topic", "action": "chat", "execution_mode": "chat"},
    )
    assert response.status_code == 202
    for _ in range(6):
        if step() is None:
            break
    response = saved[0].post(
        f"/api/chat/conversations/{saved[1]}/messages",
        json={"content": "Describe it", "execution_mode": "chat"},
    )
    assert response.status_code == 202, response.text
    assert not response.json()["parameters"].get("image_artifact_ids")


def test_another_conversation_cannot_acquire_the_agent_image(saved, image_result):
    other = (
        saved[0]
        .post("/api/chat/conversations", json={"execution_mode": "work", "model": "fake-local"})
        .json()["id"]
    )
    response = saved[0].post(
        f"/api/chat/conversations/{other}/messages", json={"content": "Powiększ ten obraz"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("state", ["needs_review", "failed"])
def test_latest_image_agent_without_a_published_result_never_uses_an_older_image(saved, image_result, state):
    from app.models import Agent
    from test_conversation_agent_control import send

    with session_factory()() as db:
        agent = db.get(Agent, saved[2])
        agent.tools = ["create_media"]
        agent.media = {"kind": "image", "request": {"mode": "t2i", "prompt": "Another image"}}
        agent.enabled = False
        agent.updated_at = utcnow()
        db.commit()
    queued = send(saved)
    step()
    if state == "failed":
        with session_factory()() as db:
            control = db.get(Run, queued["id"])
            control.status = "failed"
            control.metadata_json = {}
            from sqlalchemy import select

            response = db.scalar(
                select(Message).where(Message.run_id == control.id, Message.role == "assistant")
            )
            response.metadata_json = {
                key: value for key, value in response.metadata_json.items() if key != "agent_control_result"
            }
            db.commit()
    request = saved[0].post(
        f"/api/chat/conversations/{saved[1]}/messages", json={"content": "Powiększ ten obraz"}
    )
    assert request.status_code == 422, request.text


def test_agent_image_changed_after_send_is_not_dispatched(saved, image_result):
    _, _, aid = image_result
    accepted = saved[0].post(
        f"/api/chat/conversations/{saved[1]}/messages", json={"content": "Powiększ ten obraz"}
    )
    assert accepted.status_code == 202, accepted.text
    with session_factory()() as db:
        artifact = db.get(Artifact, aid)
        safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed after Send")
    step()
    with session_factory()() as db:
        run = db.get(Run, accepted.json()["id"])
        assert run.status == "failed"
        from sqlalchemy import select

        assert not list(db.scalars(select(Run).where(Run.parent_run_id == run.id)))
