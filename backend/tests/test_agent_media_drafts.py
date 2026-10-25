"""Natural drafting preserves a reviewable output scope, never media execution."""

import json
from uuid import uuid4

import pytest
from app.agent_drafts import Proposal, definition
from app.api import app
from app.db import session_factory
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_drafts import model as model
from test_agent_drafts import state, step, submit
from test_agent_media import implemented_media as implemented_media


@pytest.mark.parametrize("kind", ["image", "music", "video", "avatar"])
def test_media_draft_publishes_disabled_settings_without_generation(model, implemented_media, kind):
    calls, responses = model
    request = {
        "image": {"mode": "t2i", "prompt": "New forest illustration"},
        "music": {"caption": "Calm piano", "duration_seconds": 60},
        "video": {"prompt": "Quiet forest film", "duration_seconds": 30},
        "avatar": {
            "speech_text": "Write a short Polish welcome",
            "image_artifact_id": None,
            "audio_artifact_id": None,
        },
    }[kind]
    responses[:] = [
        json.dumps(
            {
                "name": "Daily creative output",
                "goal": "Create a fresh local result every morning",
                "tools": ["create_media"],
                "media": {"kind": kind, "description_source": "goal", "request": request},
                "trigger": "cron",
                "cron_expr": "0 8 * * *",
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(api, instruction="Create a fresh local image or music each morning at 08:00 UTC")
        assert step() == run["id"]
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["media"]["kind"] == kind
        assert agent["media"]["description_source"] == "goal"
        assert agent["tools"] == ["create_media"]
        assert not agent["enabled"] and agent["next_run_at"] is None
        assert agent["cron_expr"] == "0 8 * * *"
        prompt = json.loads(calls[0]["messages"][1]["content"])
        assert "create_media" in prompt["operational_local_tools"]
        if kind in {"video", "avatar"}:
            assert prompt["proposal_schema"]["properties"]["maximum_runtime"]["default"] is None
            assert agent["maximum_runtime"] == (14400 if kind == "video" else 7200)
        if kind == "video":
            properties = prompt["proposal_schema"]["$defs"]["AgentVideoRequest"]["properties"]
            # Real local inference copied the advertised short-clip default into
            # a duration-based film, then failed both bounded correction attempts.
            assert "duration_seconds" in properties
            assert "frames" not in properties
            assert "client_request_id" not in properties
        with session_factory()() as session:
            assert [r.executor_type for r in session.scalars(select(Run))] == ["agent_draft"]


def test_media_proposals_require_scope_reviewed_inputs_and_supplied_lyrics(implemented_media):
    base = {"name": "Output", "goal": "Create music", "tools": ["create_media"]}
    with pytest.raises(ValueError, match="reviewable"):
        definition(Proposal(**base), "Create music", "fake-local")
    with pytest.raises(ValueError, match="Library references"):
        definition(
            Proposal(
                **base,
                media={
                    "kind": "image",
                    "request": {
                        "mode": "img2img",
                        "edit_prompt": "Change clothes",
                        "input_artifact_ids": [str(uuid4())],
                    },
                },
            ),
            "Edit an image",
            "fake-local",
        )
    vocal = {
        "kind": "music",
        "request": {
            "caption": "Folk",
            "instrumental": False,
            "lyrics": "[Verse]\nMorning light",
        },
    }
    with pytest.raises(ValueError, match="supplied"):
        definition(Proposal(**base, media=vocal), "Create a song", "fake-local")
    result = definition(Proposal(**base, media=vocal), "Sing [Verse]\nMorning light", "fake-local")
    assert result.media.request.lyrics == vocal["request"]["lyrics"]
    assert result.model == "" and not result.enabled


def test_natural_vocal_agent_can_review_goal_lyrics_without_inventing_supplied_words(implemented_media):
    candidate = Proposal(
        name="Morning song",
        goal="Write and sing a short original Polish song",
        tools=["create_media"],
        media={
            "kind": "music",
            "description_source": "goal",
            "lyrics_source": "goal",
            "request": {
                "caption": "Acoustic Polish folk",
                "duration_seconds": 30,
                "instrumental": False,
                "lyrics": "",
            },
        },
    )
    result = definition(
        candidate, "Create an agent that writes and sings a new Polish song each morning", "fake-local"
    )
    assert not result.enabled and result.model == "fake-local"
    assert result.media.lyrics_source == "goal" and result.media.request.lyrics == ""


@pytest.mark.parametrize("duration,expected", [(5, 7200), (15, 7200), (16, 14400), (60, 14400)])
@pytest.mark.parametrize("nullable", [False, True])
def test_fresh_video_draft_runtime_fits_full_output_without_changing_media(
    implemented_media, duration, expected, nullable
):
    media = {
        "kind": "video",
        "description_source": "goal",
        "request": {"prompt": "A quiet lake", "duration_seconds": duration, "seed": 51},
    }
    values = {"name": "Lake film", "goal": "Generate a lake film", "tools": ["create_media"], "media": media}
    if nullable:
        values["maximum_runtime"] = None
    result = definition(Proposal(**values), "Create an agent making a lake film", "fake-local")
    assert result.maximum_runtime == expected
    assert result.media.request.duration_seconds == duration
    assert result.media.request.seed == 51
    assert result.media.request.memory_profile == "default"
    assert not result.enabled and result.tools == ["create_media"]


@pytest.mark.parametrize("seconds", [5, 300, 600, 14400])
@pytest.mark.parametrize("kind", ["video", "avatar"])
def test_explicit_media_draft_runtime_is_preserved_even_when_short(implemented_media, seconds, kind):
    proposal = Proposal(
        name="Bounded film",
        goal="Generate within the explicit allowance",
        tools=["create_media"],
        maximum_runtime=seconds,
        media={
            "kind": kind,
            "request": {"prompt": "Quiet lake", "duration_seconds": 30} if kind == "video" else {},
        },
    )
    result = definition(proposal, f"Create a video agent with a {seconds}-second runtime limit", "fake-local")
    assert result.maximum_runtime == seconds
    assert not result.enabled


@pytest.mark.parametrize(
    "instruction,tools,expected",
    [
        ("Create an agent reporting workstation telemetry", ["system_snapshot"], 600),
        ("Create an agent that builds a new website", ["coding_local"], 1800),
    ],
)
def test_unspecified_non_media_runtime_keeps_existing_factory_defaults(instruction, tools, expected):
    proposal = Proposal(name="Useful agent", goal=instruction, tools=tools)
    result = definition(proposal, instruction, "fake-local")
    assert result.maximum_runtime == expected
    assert not result.enabled and result.tools == tools
