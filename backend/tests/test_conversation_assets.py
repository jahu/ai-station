import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.models import Artifact, Conversation, Message, Run
from app.runs import create_run, create_task
from app.vision_inputs import freeze
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_assistant_controller import drain, finish, submit, tool
from test_assistant_controller import model as model
from test_images import bridge as bridge
from test_images import upload


def followup(api, cid, text):
    response = api.post(
        "/api/chat/conversations/" + cid + "/messages",
        json={"content": text, "execution_mode": "assistant", "web_search": {"enabled": False}},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_attachment_survives_a_clarification_and_intervening_text_turn(model, bridge):
    model["outcomes"] = [
        {
            "kind": "image",
            "count": 1,
            "description": "A changed cabinet",
            "reference_mode": "provided",
            "source_inputs": ["input:image:1"],
        }
    ]
    model["decisions"] = [
        {"kind": "clarify", "reason": "Choose the scene", "response": "Do you prefer a garden or a studio?"}
    ]
    with TestClient(app) as api:
        source = upload(api)["id"]
        first = submit(api, "Change the scene, but ask which one before editing", image_artifact_ids=[source])
        drain()
        model["outcomes"] = [{"kind": "text", "count": 1, "description": "An explanation"}]
        model["decisions"] = [tool("chat.reply", instruction="Explain the two scene choices")]
        followup(api, first["conversation_id"], "What would a garden version look like?")
        drain()
        model["outcomes"] = [
            {
                "kind": "image",
                "count": 1,
                "description": "The same cabinet in a garden",
                "reference_mode": "provided",
                "source_inputs": ["previous:image:1"],
            }
        ]
        model["decisions"] = [
            tool(
                "image.recompose",
                instruction="Put the same cabinet in a sunny garden",
                images=["previous:image:1"],
            ),
            finish(1),
        ]
        third = followup(api, first["conversation_id"], "The garden, please. Edit the image now.")
        with session_factory()() as db:
            root = db.get(Run, third["id"])
            assert [item["snapshot"]["id"] for item in root.parameters["controller_inputs"]] == [source]
            assert any(
                row["role"] == "assistant" and row["content"] == "Do you prefer a garden or a studio?"
                for row in root.parameters["planner_context"]
            )
        drain()
        with session_factory()() as db:
            photo = db.scalar(select(Run).where(Run.executor_type == "photo_pipe"))
            assert (
                photo.parameters["parent_artifact_ids"] == [source]
                and db.get(Run, third["id"]).status == "succeeded"
            )


def legacy_upload(api):
    aid = upload(api)["id"]
    with session_factory()() as db:
        conversation = Conversation(model="test-model", execution_mode="assistant")
        db.add(conversation)
        db.flush()
        task = create_task(
            db,
            title="Legacy image question",
            prompt="Here is the cabinet",
            capability="chat.vision",
            conversation_id=conversation.id,
        )
        run = create_run(
            db,
            task,
            run_type="chat",
            capability="chat.vision",
            executor_type="vision",
            parameters={"image_inputs": freeze(db, [aid])},
        )
        run.status = "succeeded"
        user = Message(
            conversation_id=conversation.id,
            role="user",
            content="Here is the cabinet",
            run_id=run.id,
            metadata_json={"images": [{"id": aid, "name": "cabinet.png"}]},
        )
        db.add(user)
        db.commit()
        return conversation.id, aid


@pytest.mark.parametrize("change", [None, "hash", "trash"])
def test_legacy_attachment_is_recovered_only_when_its_frozen_source_is_still_valid(model, bridge, change):
    with TestClient(app) as api:
        cid, aid = legacy_upload(api)
        if change:
            with session_factory()() as db:
                artifact = db.get(Artifact, aid)
                if change == "hash":
                    artifact.sha256 = "0" * 64
                else:
                    artifact.trashed_at = utcnow()
                db.commit()
        result = followup(api, cid, "Please modify the earlier image")
        with session_factory()() as db:
            root = db.get(Run, result["id"])
            entries = root.parameters["controller_inputs"]
            assert [item["snapshot"]["id"] for item in entries] == ([] if change else [aid])


def test_new_attachment_is_the_active_reference_without_losing_the_old_original(model, bridge):
    from app.assistant_controller import decision_context

    with TestClient(app) as api:
        cid, original = legacy_upload(api)
        new = upload(api)["id"]
        response = api.post(
            "/api/chat/conversations/" + cid + "/messages",
            json={
                "content": "Use this new image instead",
                "execution_mode": "assistant",
                "image_artifact_ids": [new],
                "web_search": {"enabled": False},
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as db:
            root = db.get(Run, response.json()["id"])
            context = decision_context(db, root)
            assert context["reference_context"]["active_images"] == ["input:image:1"]
            assert {item["snapshot"]["id"] for item in root.parameters["controller_inputs"]} == {
                original,
                new,
            }
