"""A talking-avatar video can fulfill a video request, without double counting."""

import pytest
from app.api import app
from app.assistant_controller import missing_outcomes
from fastapi.testclient import TestClient
from test_assistant_controller import drain, finish, root_state, submit, tool
from test_assistant_controller import model as model
from test_whole_avatar_jobs import bridge as bridge
from test_whole_avatars import sources as sources


@pytest.mark.parametrize(
    "requested, produced, missing",
    [
        (["video"], ["avatar"], []),
        (["avatar"], ["avatar"], []),
        (["avatar"], ["video"], ["avatar"]),
        (["video", "avatar"], ["avatar"], ["video"]),
        (["avatar", "video"], ["avatar"], ["video"]),
        (["video", "avatar"], ["avatar", "avatar"], []),
        (["avatar", "video"], ["video", "avatar"], []),
    ],
)
def test_video_subtype_consumes_one_actual_output(requested, produced, missing):
    outcomes = [{"kind": kind, "count": 1, "description": "Requested media"} for kind in requested]
    observations = [
        {
            "tool": "avatar.animate" if kind == "avatar" else "video.generate",
            "status": "succeeded",
            "produced_types": ["video"],
        }
        for kind in produced
    ]
    assert [item["kind"] for item in missing_outcomes(observations, outcomes)] == missing


@pytest.mark.parametrize(
    "status, types", [("failed", ["video"]), ("running", ["video"]), ("succeeded", ["audio"])]
)
def test_avatar_without_a_successful_video_cannot_fulfill_video(status, types):
    observations = [{"tool": "avatar.animate", "status": status, "produced_types": types}]
    outcomes = [{"kind": "video", "count": 1, "description": "A video"}]
    assert missing_outcomes(observations, outcomes)[0]["remaining"] == 1


def test_two_requested_videos_require_two_completed_outputs():
    observations = [{"tool": "avatar.animate", "status": "succeeded", "produced_types": ["video"]}]
    outcomes = [{"kind": "video", "count": 2, "description": "Two videos"}]
    assert missing_outcomes(observations, outcomes)[0]["remaining"] == 1


@pytest.mark.parametrize("kind", ["video", "avatar"])
def test_avatar_tool_can_finish_both_valid_intent_types_without_an_extra_action(model, bridge, kind):
    inputs, native = bridge
    model["outcomes"] = [{"kind": kind, "count": 1, "description": "A speaking portrait film"}]
    model["decisions"] = [
        tool(
            "avatar.animate",
            instruction="Animate the supplied portrait with the supplied recording",
            images=["input:image:1"],
            audio="input:audio:1",
        ),
        finish(1),
    ]
    with TestClient(app) as client:
        receipt = submit(
            client,
            "Make a speaking portrait film from these two inputs",
            image_artifact_ids=[inputs[0]],
            audio_artifact_id=inputs[1],
        )
        drain()
        state = root_state(receipt)
        assert state["controller_outcome"] == "finish"
        assert len(state["controller_steps"]) == 1
        assert state["controller_steps"][0]["observation"]["produced_types"] == ["video"]
        assert len(native["whole"]) == 1 and not model["decisions"]
        messages = client.get("/api/chat/conversations/" + receipt["conversation_id"]).json()["messages"]
        assert any(row["content"] == "The requested results are ready." for row in messages)
