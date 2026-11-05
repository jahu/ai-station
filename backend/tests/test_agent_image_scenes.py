import json
from datetime import timedelta

import pytest
from app.agent_image_scenes import ImageScene, recent_scenes
from app.agent_media_schema import AgentImageScope
from app.api import app
from app.db import session_factory, utcnow
from app.local_provider import LocalChatProvider
from app.models import Agent, Run, Task
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create, drain, start
from test_agent_media import implemented_media as implemented_media
from test_images import bridge as bridge
from test_images import upload

A = {
    "description": "Soft daylight, a blue jacket, realistic portrait",
    "setting": "A quiet cafe with tall windows",
    "pose": "Sitting sideways on a chair, hands on the table",
    "expression": "Broad smile, raised eyebrows",
}
B = {
    "description": "Evening light, a blue jacket, realistic portrait",
    "setting": "A leafy garden beside a stone wall",
    "pose": "Standing upright, left hand resting on a railing",
    "expression": "Thoughtful gaze, relaxed closed lips",
}


def test_recurring_scenes_use_completed_history_retry_duplicates_and_keep_reviewed_settings(
    implemented_media, bridge, monkeypatch
):
    calls = []
    answers = iter([A, A, B, B, B])

    async def describe(self, **kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        calls.append(payload)
        assert (
            "prompt" not in payload["scope"]["request"] and "edit_prompt" not in payload["scope"]["request"]
        )
        assert "not a report" in kwargs["messages"][0]["content"]
        assert kwargs["temperature"] == 0.8
        yield json.dumps(next(answers))

    monkeypatch.setattr(LocalChatProvider, "stream", describe)
    with TestClient(app) as api:
        source = upload(api)["id"]
        agent = create(
            api,
            kind="image",
            goal="Keep the reference person, vary their setting, pose and expression",
            model="fake-local",
            media={
                "kind": "image",
                "description_source": "goal",
                "vary_scenes": True,
                "request": {
                    "mode": "recompose",
                    "prompt_style": "instruction",
                    "prompt": "Keep the reference person, vary their setting, pose and expression",
                    "input_artifact_ids": [source],
                    "seed": None,
                    "gpu": "7",
                    "width": 256,
                    "height": 256,
                    "steps": 1,
                },
            },
        )
        roots = []
        for _ in range(3):
            roots.append(start(api, api.get("/api/agents/" + agent["id"]).json()))
            with session_factory()() as db:
                drain(db)
        with session_factory()() as db:
            images = list(
                db.scalars(
                    select(Run)
                    .where(Run.agent_id == agent["id"], Run.capability == "image.recompose")
                    .order_by(Run.created_at)
                )
            )
            assert len(images) == 2 and all(row.status == "succeeded" for row in images)
            assert images[0].parameters["prompt"] == ImageScene(**A).image_prompt()
            assert images[1].parameters["prompt"] == ImageScene(**B).image_prompt()
            assert all(
                row.parameters["seed"] is None
                and row.requested_resources["gpu"] == "7"
                and row.parameters["prompt_style"] == "instruction"
                for row in images
            )
            failed = list(
                db.scalars(
                    select(Run).where(Run.task_id == roots[-1]["task_id"], Run.executor_type == "agent_media")
                )
            )
            assert len(failed) == 1 and failed[0].status == "failed"
        assert calls[0]["previous_scenes"] == []
        assert calls[1]["previous_scenes"][0]["run_id"] == images[0].id
        assert len(calls[-1]["previous_scenes"]) == 2
        assert calls[0]["additional_visual_guidance"] == ""


@pytest.mark.parametrize(
    "problem", ["owner", "agent", "reference", "failed_child", "failed_preparation", "different_parent"]
)
def test_history_excludes_other_owners_agents_references_and_unsuccessful_outputs(session, problem):
    from app.models import User

    user = User(username="PortraitOwner", normalized_username="portraitowner")
    other = User(username="OtherOwner", normalized_username="otherowner")
    session.add_all([user, other])
    session.flush()
    agent = Agent(name="Portrait series", goal="Neutral portraits", owner_id=user.id)
    other_agent = Agent(name="Other series", goal="Landscapes", owner_id=user.id)
    session.add_all([agent, other_agent])
    session.flush()
    task = Task(title="Portrait fixture", owner_id=user.id)
    session.add(task)
    session.flush()
    inputs = [{"id": "source", "sha256": "a" * 64}]
    prior = Run(
        task_id=task.id,
        agent_id=agent.id,
        owner_id=user.id,
        executor_type="agent_media",
        status="succeeded",
        created_at=utcnow() - timedelta(minutes=1),
        parameters={"media_inputs": inputs, "image_scene": A},
    )
    session.add(prior)
    session.flush()
    child = Run(
        task_id=task.id,
        parent_run_id=prior.id,
        agent_id=agent.id,
        owner_id=user.id,
        capability="image.recompose",
        status="succeeded",
    )
    current = Run(task_id=task.id, agent_id=agent.id, owner_id=user.id, parameters={"media_inputs": inputs})
    session.add_all([child, current])
    session.flush()
    prior.metadata_json = {"media_run_id": child.id}
    session.flush()
    assert len(recent_scenes(session, current)) == 1
    if problem == "owner":
        prior.owner_id = other.id
    elif problem == "agent":
        prior.agent_id = other_agent.id
    elif problem == "reference":
        prior.parameters = {**prior.parameters, "media_inputs": [{"id": "different", "sha256": "b" * 64}]}
    elif problem == "failed_child":
        child.status = "failed"
    elif problem == "failed_preparation":
        prior.status = "failed"
    else:
        child.parent_run_id = None
    session.flush()
    assert recent_scenes(session, current) == []


def test_legacy_scope_serialization_is_unchanged_and_new_scenes_require_reviewed_operation():
    scope = {"kind": "image", "request": {"mode": "t2i", "prompt": "A quiet park"}}
    assert "vary_scenes" not in AgentImageScope.model_validate(scope).model_dump()
    for change in [{"vary_scenes": True}, {"vary_scenes": "true"}]:
        with pytest.raises(ValueError):
            AgentImageScope.model_validate({**scope, **change})
    with pytest.raises(ValueError):
        ImageScene(**{**A, "pose": "a different pose"})
