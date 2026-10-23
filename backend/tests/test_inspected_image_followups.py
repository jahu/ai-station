"""Image follow-ups select verified pixels from this conversation, not model text."""

from pathlib import Path
from uuid import uuid4

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory, utcnow
from app.local_provider import LocalChatProvider
from app.models import Artifact, Message, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_conversation_media import completed_image
from test_vision import setup, step
from test_vision import vision_runtime as vision_runtime


def inspected(client, monkeypatch, *, count=1, conversation_id=None):
    async def stream(self, **params):
        yield "The selected image is red."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    cid, image = setup(client)
    cid = conversation_id or cid
    ids = [image]
    for _ in range(count - 1):
        _, another = setup(client)
        ids.append(another)
    response = client.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Describe these images", "action": "image.describe", "image_artifact_ids": ids},
    )
    assert response.status_code == 202, response.text
    for _ in range(4):
        step()
    with session_factory()() as session:
        root = session.get(Run, response.json()["id"])
        child = session.scalar(
            select(Run).where(Run.parent_run_id == root.id, Run.capability == "chat.vision")
        )
        assert child.status == root.status == "succeeded"
        result = session.scalar(select(Artifact).where(Artifact.run_id == child.id))
        return cid, ids, root.id, child.id, result.id


@pytest.mark.parametrize(
    ("prompt", "action"),
    [
        ("Zmień to zdjęcie na portret w zimowym ubraniu", "image.edit"),
        ("Edit this image: add a blue hat", "image.edit"),
        ("Change this picture into a watercolor portrait", "image.edit"),
        ("Powiększ to zdjęcie", "image.upscale"),
        ("Opisz ten obraz", "image.describe"),
        ("Animate this image", "video.generate"),
    ],
)
def test_current_inspected_input_is_selected_and_receipt_replays(vision_runtime, monkeypatch, prompt, action):
    with TestClient(app) as client:
        cid, ids, _, vision_id, _ = inspected(client, monkeypatch)
        request = {
            "content": prompt,
            "conversation_id": cid,
            "client_request_id": str(uuid4()),
            "expected_settings_version": 1,
            "web_search": {"enabled": True},
        }
        response = client.post("/api/chat/turns", json=request)
        assert response.status_code == 202, response.text
        run = response.json()["run"]
        assert run["parameters"]["action"] == action
        assert run["parameters"]["image_artifact_ids"] == ids
        assert not run["parameters"]["web_search"]["enabled"]
        assert "external_ai" not in run["effective_permissions"]
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        user = next(m for m in detail["messages"] if m["id"] == response.json()["user_message_id"])
        reference = user["metadata"]["conversation_reference"]
        assert reference["source_kind"] == "inspected_input"
        assert reference["artifact_ids"] == ids
        assert reference["run_id"] == vision_id
        assert client.post("/api/chat/turns", json=request).json()["run"]["id"] == run["id"]
        monkeypatch.setattr("app.video.capabilities", lambda: {"available": True})
        step()  # Existing child contracts only; never execute native image/video inference.
        with session_factory()() as session:
            children = list(session.scalars(select(Run).where(Run.parent_run_id == run["id"])))
            current = session.get(Run, run["id"])
            assert children, (current.status, current.error_message, current.metadata_json)
            assert current.status != "failed", current.error_message


@pytest.mark.parametrize("prompt", ["Opisz te zdjęcia", "Zmień te zdjęcia na portret w zimowym ubraniu"])
def test_explicit_group_preserves_input_order(vision_runtime, monkeypatch, prompt):
    with TestClient(app) as client:
        cid, ids, _, _, _ = inspected(client, monkeypatch, count=2)
        response = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": prompt})
        assert response.status_code == 202, response.text
        assert response.json()["parameters"]["image_artifact_ids"] == ids
        assert response.json()["parameters"]["action"] == (
            "image.describe" if prompt.startswith("Opisz") else "image.recompose"
        )


@pytest.mark.parametrize(
    "problem",
    [
        "group",
        "trashed",
        "bytes",
        "symlink",
        "path",
        "snapshot",
        "legacy",
        "child",
        "user",
        "result",
        "partial",
    ],
)
def test_invalid_current_source_rejects_without_a_new_run(vision_runtime, monkeypatch, problem):
    with TestClient(app) as client:
        cid, ids, root_id, child_id, result_id = inspected(
            client, monkeypatch, count=2 if problem == "group" else 1
        )
        with session_factory()() as session:
            image = session.get(Artifact, ids[0])
            root, child = session.get(Run, root_id), session.get(Run, child_id)
            if problem == "trashed":
                image.trashed_at = utcnow()
            elif problem in {"bytes", "symlink"}:
                path = get_settings().data_dir / image.relative_path
                if problem == "bytes":
                    path.write_bytes(b"changed")
                else:
                    other = path.with_suffix(".original")
                    path.rename(other)
                    path.symlink_to(other)
            elif problem == "path":
                image.relative_path = str(Path("/tmp/foreign-image.png"))
            elif problem == "snapshot":
                image.sha256 = "0" * 64
            elif problem == "legacy":
                root.parameters = {k: v for k, v in root.parameters.items() if k != "image_inputs"}
            elif problem == "child":
                child.parent_run_id = None
            elif problem == "user":
                user = session.get(Message, root.parameters["user_message_id"])
                user.metadata_json = {**user.metadata_json, "images": []}
            elif problem == "result":
                result = session.get(Artifact, result_id)
                (get_settings().data_dir / result.relative_path).write_text("tampered")
            elif problem == "partial":
                message = session.scalar(
                    select(Message).where(Message.run_id == root_id, Message.role == "assistant")
                )
                message.metadata_json = {**message.metadata_json, "partial": True}
            before = len(list(session.scalars(select(Run))))
            session.commit()
        response = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Upscale this image"}
        )
        assert response.status_code == 422, response.text
        with session_factory()() as session:
            assert len(list(session.scalars(select(Run)))) == before


def test_other_conversation_does_not_grant_input(vision_runtime, monkeypatch):
    with TestClient(app) as client:
        inspected(client, monkeypatch)
        cid, _ = setup(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Upscale this image"}
        )
        assert response.status_code == 422, response.text


def test_source_changed_during_inference_cannot_publish_inspected_result(vision_runtime, monkeypatch):
    with TestClient(app) as client:
        cid, image_id = setup(client)

        async def stream(self, **params):
            with session_factory()() as session:
                image = session.get(Artifact, image_id)
                (get_settings().data_dir / image.relative_path).write_bytes(b"changed during inference")
            yield "This must remain an unverified partial response."

        monkeypatch.setattr(LocalChatProvider, "stream", stream)
        client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Describe image", "action": "image.describe", "image_artifact_ids": [image_id]},
        )
        for _ in range(4):
            step()
        with session_factory()() as session:
            child = session.scalar(select(Run).where(Run.capability == "chat.vision"))
            assert child.status == "failed"
            assert not session.scalar(select(Artifact).where(Artifact.run_id == child.id))


def test_new_invalid_inspection_cannot_fall_back_to_older_generated_image(vision_runtime, monkeypatch):
    with TestClient(app) as client:
        cid, _ = setup(client)
        completed_image(client, cid)
        _, ids, _, _, _ = inspected(client, monkeypatch, conversation_id=cid)
        with session_factory()() as session:
            session.get(Artifact, ids[0]).trashed_at = utcnow()
            session.commit()
        response = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Upscale this image"}
        )
        assert response.status_code == 422, response.text


def test_new_generated_output_wins_over_older_inspected_input(vision_runtime, monkeypatch):
    with TestClient(app) as client:
        cid, _, _, _, _ = inspected(client, monkeypatch)
        output, producer = completed_image(client, cid)
        step()
        response = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Upscale this image"}
        )
        assert response.status_code == 202, response.text
        assert response.json()["parameters"]["image_artifact_ids"] == [output]
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        user = next(
            m for m in detail["messages"] if m["run_id"] == response.json()["id"] and m["role"] == "user"
        )
        assert user["metadata"]["conversation_reference"]["run_id"] == producer
        assert "source_kind" not in user["metadata"]["conversation_reference"]


@pytest.mark.parametrize("change_at", ["before_publication", "before_dispatch"])
def test_queued_edit_rechecks_pixels_before_native_execution(vision_runtime, monkeypatch, change_at):
    from app.runner_client import RunnerClient

    started = []
    monkeypatch.setattr(RunnerClient, "start_photo", lambda *args: started.append(args))
    with TestClient(app) as client:
        cid, ids, _, _, _ = inspected(client, monkeypatch)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Edit this image: add a blue hat"}
        )
        assert response.status_code == 202, response.text
        if change_at == "before_dispatch":
            step()
            # An unoccupied fake GPU admits the child; the Vision runtime owns GPU 7.
            monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"gpus": [{"index": 8}]})
        with session_factory()() as session:
            image = session.get(Artifact, ids[0])
            (get_settings().data_dir / image.relative_path).write_bytes(b"changed while waiting")
        step()
        assert not started
        with session_factory()() as session:
            root = session.get(Run, response.json()["id"])
            children = list(session.scalars(select(Run).where(Run.parent_run_id == root.id)))
            if change_at == "before_publication":
                assert root.status == "failed"
                assert not children
            else:
                assert len(children) == 1
                assert children[0].status == "failed", children[0].error_message
                assert children[0].parameters["inspected_image_inputs"][0]["artifact_id"] == ids[0]
