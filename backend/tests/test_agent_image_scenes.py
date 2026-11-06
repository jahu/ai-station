import json
from datetime import timedelta

import pytest
from app.agent_image_scenes import ImageVariation, history_variations, recent_scenes, repeats
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
    "description": "Keep the reference wardrobe's oak finish and brass hardware. Show it in a bright hallway, three-quarter view, with soft daylight.",
    "preserve": ["oak finish", "brass hardware"],
    "changes": {"setting": "A bright hallway with pale walls", "composition": "Three-quarter product view"},
}
B = {
    "description": "Keep the reference wardrobe's oak finish and brass hardware. Show it front-on in a quiet bedroom under warm diffuse light.",
    "preserve": ["oak finish", "brass hardware"],
    "changes": {"setting": "A quiet bedroom with a woven rug", "composition": "Straight-on product view"},
}


def test_recurring_scenes_use_completed_history_retry_duplicates_and_keep_reviewed_settings(
    implemented_media, bridge, monkeypatch
):
    calls = []
    requests = []
    answers = iter([A, A, B, B, B])

    async def describe(self, **kwargs):
        requests.append(kwargs["messages"])
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
            goal="Create varied images of this wardrobe; keep its oak finish and brass hardware",
            model="fake-local",
            media={
                "kind": "image",
                "description_source": "goal",
                "vary_scenes": True,
                "request": {
                    "mode": "recompose",
                    "prompt_style": "instruction",
                    "prompt": "Create varied images of this wardrobe; keep its oak finish and brass hardware",
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
            assert images[0].parameters["prompt"] == ImageVariation(**A).image_prompt()
            assert images[1].parameters["prompt"] == ImageVariation(**B).image_prompt()
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
            assert "new image variation" in failed[0].error_message
            prepared = db.scalar(
                select(Run).where(Run.task_id == roots[1]["task_id"], Run.executor_type == "agent_media")
            )
            assert prepared.parameters["image_scene_history"][0]["description"] == A["description"]
        assert calls[0]["previous_scenes"] == []
        assert calls[1]["previous_scenes"][0]["run_id"] == images[0].id
        assert calls[1]["previous_scenes"][0]["changes"] == A["changes"]
        assert "description" not in calls[1]["previous_scenes"][0]
        assert "preserve" not in calls[1]["previous_scenes"][0]
        assert [item["role"] for item in requests[2]] == ["system", "user", "user"]
        feedback = json.loads(requests[2][-1]["content"])
        assert feedback["rejected_changes"] == A["changes"]
        assert "at least one genuinely different" in feedback["requirement"]
        assert A["description"] not in json.dumps(requests[2])
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
        ImageVariation(**{**A, "changes": {"composition": "a different view"}})


@pytest.mark.parametrize(
    "description,changes",
    [
        ("An oak wardrobe in a bright hallway", {"setting": "A bright hallway"}),
        ("The reference building at dusk, preserving its facade", {"lighting": "Diffuse evening light"}),
        ("The same illustrated mark printed on textured paper", {"presentation": "Textured cream paper"}),
        ("A relaxed portrait of the reference subject by a window", {"lighting": "Soft window light"}),
    ],
)
def test_compiled_prompt_does_not_inject_a_subject_medium_or_anatomy(description, changes):
    plan = ImageVariation(description=description, changes=changes)
    prompt = plan.image_prompt()
    assert prompt.startswith(description)
    assert all(direction in prompt for direction in changes.values())
    assert "same person" not in prompt and "photograph" not in prompt


def test_compilation_cannot_drop_planned_changes_missing_from_the_freeform_description():
    plan = ImageVariation(
        description="A product image of the wardrobe",
        preserve=["oak finish", "brass hardware"],
        changes={"lighting": "Green light from the left", "setting": "A dark blue studio"},
    )
    prompt = plan.image_prompt()
    assert "Green light from the left" in prompt and "A dark blue studio" in prompt
    assert all(value in prompt for value in plan.preserve)
    assert "relative to the references" in prompt


def test_repeat_detection_checks_both_the_actual_prompt_and_the_change_plan():
    assert repeats({**A, "changes": B["changes"]}, [A])
    assert repeats({**A, "description": "A paraphrase of the same idea"}, [A])
    assert not repeats(B, [A])
    with pytest.raises(ValueError):
        ImageVariation(**{**A, "changes": {"Lighting": "Soft daylight", "lighting": "Hard direct flash"}})


def test_old_saved_plans_and_frozen_histories_remain_readable_without_mutation():
    old = {
        "run_id": "previous",
        "description": "Neutral portrait",
        "setting": "A quiet cafe",
        "pose": "Sitting by the window",
        "expression": "A relaxed smile",
    }
    snapshot = json.loads(json.dumps(old))
    converted = history_variations([old])
    assert converted[0]["run_id"] == "previous"
    assert converted[0]["changes"]["setting"] == "A quiet cafe"
    assert old == snapshot


def test_complete_structured_variation_does_not_require_redundant_prose():
    plan = ImageVariation(
        preserve=["Oak finish"],
        changes={"setting": "A sunny garden", "composition": "Side view beside a fountain"},
    )
    prompt = plan.image_prompt()
    assert "Oak finish" in prompt and "sunny garden" in prompt and "Side view" in prompt
    assert not prompt.startswith("\n")
