"""Durable model-aware retries, separate variants and genuine clarification."""

import json

import pytest
from app.api import app
from app.assistant_controller import controller_results
from app.db import session_factory
from app.models import Artifact, Message, Run, RunEvent
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_assistant_controller import drain, root_state, submit
from test_assistant_react_workflow import action
from test_assistant_react_workflow import react_model as react_model
from test_images import bridge as bridge
from test_images import upload


def outcomes(alias, grouped):
    first = {
        "kind": "image",
        "description": "A new viewpoint of the same reference subject",
        "reference_mode": "provided",
        "source_inputs": [alias],
    }
    return (
        [{**first, "count": 2}]
        if grouped
        else [first, {**first, "description": "A second different viewpoint of the same reference subject"}]
    )


@pytest.mark.parametrize("grouped", [False, True])
def test_two_separate_variants_repair_an_unsupported_hint_without_switching_model_or_reference(
    react_model, bridge, grouped
):
    react_model["immediate"] = outcomes("input:image:1", grouped)
    react_model["actions"] = [
        action(
            "image_recompose",
            instruction="First new viewpoint",
            images=["input:image:1"],
            reference_layout="beside",
        ),
        action("image_recompose", instruction="First new viewpoint", images=["input:image:1"]),
        action("image_recompose", instruction="Second different viewpoint", images=["input:image:1"]),
        "Thought: Finished both requested images.\nAnswer: Two separate views are ready.",
    ]
    with TestClient(app) as api:
        original = upload(api)["id"]
        result = submit(
            api,
            "Create two separate pictures of this cabinet from different viewpoints, preserving its distinctive details",
            image_artifact_ids=[original],
        )
        drain()
        state = root_state(result)
        assert state["controller_outcome"] == "finish"
        assert [x["tool"] for x in state["controller_steps"]] == ["image.recompose", "image.recompose"]
        with session_factory()() as db:
            photos = list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))
            assert len(photos) == 2 and all(x.status == "succeeded" for x in photos)
            assert all(
                x.parameters["backend"] == "qwen" and x.parameters["parent_artifact_ids"] == [original]
                for x in photos
            )
            generated = list(
                db.scalars(
                    select(Artifact).where(
                        Artifact.run_id.in_([x.id for x in photos]), Artifact.artifact_type == "image"
                    )
                )
            )
            assert len(generated) == 2 and generated[0].id != generated[1].id
            decision = db.scalar(
                select(Run)
                .where(Run.parent_run_id == result["run"]["id"], Run.executor_type == "assistant_decision")
                .order_by(Run.created_at)
            )
            saved = decision.parameters["decision_attempts"][0]
            assert saved["selected_model_contract"]["model"] == "qwen"
            assert saved["rejected_action"]["arguments"]["reference_layout"] == "beside"
            event = db.scalar(
                select(RunEvent).where(
                    RunEvent.run_id == decision.id, RunEvent.event_type == "assistant.decision.rejected"
                )
            )
            assert "only to Krea2" in event.payload["validation"]
            assert "rejected_action" not in event.payload and "Thought:" not in json.dumps(event.payload)
        feedback = []
        for call in react_model["calls"]:
            message = call["messages"][-1]["content"]
            if not message.startswith("CURRENT REQUEST AND AVAILABLE STATE:"):
                continue
            current = json.loads(message.split("\n", 1)[1])
            if current.get("validation_feedback"):
                feedback.append(current)
        assert len(feedback) == 1
        assert feedback[0]["instruction"].startswith("Create two separate pictures")
        assert feedback[0]["validation_feedback"]["selected_model_contract"]["unsupported_controls"] == [
            "reference_layout"
        ]
        assert not react_model["actions"]


def test_exhausted_internal_validation_fails_without_a_false_clarification(react_model, bridge):
    react_model["immediate"] = outcomes("input:image:1", True)
    bad = action(
        "image_recompose", instruction="A new view", images=["input:image:1"], reference_layout="beside"
    )
    react_model["actions"] = [bad, bad]
    with TestClient(app) as api:
        result = submit(api, "Two separate reference-based images", image_artifact_ids=[upload(api)["id"]])
        drain()
        with session_factory()() as db:
            root = db.get(Run, result["run"]["id"])
            assert root.status == "failed" and "after correction" in root.error_message
            assert not db.scalar(select(Run.id).where(Run.executor_type == "photo_pipe"))
            decision = db.scalar(
                select(Run).where(Run.parent_run_id == root.id, Run.executor_type == "assistant_decision")
            )
            assert decision.status == "failed" and len(decision.parameters["decision_attempts"]) == 2
            assert not db.scalar(
                select(Message.id).where(
                    Message.conversation_id == root.conversation_id,
                    Message.content.contains("Please clarify the intended result"),
                )
            )


@pytest.mark.parametrize("count", [1, 2])
def test_clarification_then_requested_delivery_reuses_the_original_reference(react_model, bridge, count):
    react_model["immediate"] = outcomes("input:image:1", True)
    react_model["actions"] = [
        action("ask_user", question="Would you prefer separate files or one composite?")
    ]
    with TestClient(app) as api:
        original = upload(api)["id"]
        first = submit(
            api,
            "Prepare new views of this cabinet; ask me how to deliver them",
            image_artifact_ids=[original],
        )
        drain()
        assert root_state(first)["controller_outcome"] == "clarify"
        react_model["immediate"] = [{**outcomes("previous:image:1", True)[0], "count": count}]
        react_model["actions"] = [
            action(
                "image_recompose",
                instruction="First side view" if count == 2 else "One composite with the requested views",
                images=["previous:image:1"],
            ),
            *(
                [action("image_recompose", instruction="Second view from above", images=["previous:image:1"])]
                if count == 2
                else []
            ),
            "Thought: Requested files are complete.\nAnswer: The requested result is ready.",
        ]
        response = api.post(
            "/api/chat/conversations/" + first["conversation_id"] + "/messages",
            json={
                "content": "Two separate files, please" if count == 2 else "One composite file, please",
                "execution_mode": "assistant",
                "web_search": {"enabled": False},
            },
        )
        assert response.status_code == 202, response.text
        drain()
        with session_factory()() as db:
            root = db.get(Run, response.json()["id"])
            assert root.status == "succeeded" and root.metadata_json["controller_outcome"] == "finish"
            photos = list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))
            assert len(photos) == count and all(
                x.parameters["parent_artifact_ids"] == [original] for x in photos
            )


def test_invalid_finish_does_not_hide_an_already_completed_first_variant(react_model, bridge):
    react_model["immediate"] = outcomes("input:image:1", True)
    react_model["actions"] = [
        action("image_recompose", instruction="First view", images=["input:image:1"]),
        "Thought: Done.\nAnswer: Both are ready.",
        "Thought: Done.\nAnswer: Both are ready.",
    ]
    with TestClient(app) as api:
        result = submit(api, "Two separate cabinet images", image_artifact_ids=[upload(api)["id"]])
        drain()
        with session_factory()() as db:
            root = db.get(Run, result["run"]["id"])
            assert root.status == "failed"
            projection = controller_results(db, root)
            assert len(projection["controller_steps"]) == 1
            assert projection["controller_steps"][0]["result"]["artifacts"]
            assert sum(x["count"] for x in root.metadata_json["controller_outcomes"]) == 2
