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


@pytest.mark.parametrize("kind", ["image", "music", "video", "avatar", "effects"])
def test_media_draft_publishes_disabled_settings_without_generation(model, implemented_media, kind):
    calls, responses = model
    request = {
        "effects": {"prompt": "Wind in the trees", "video_artifact_id": None},
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
        if kind == "effects":
            assert agent["maximum_runtime"] == 1800
            assert agent["media"]["request"]["video_artifact_id"] is None
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


@pytest.mark.parametrize(
    "reference",
    [
        {"video_artifact_id": str(uuid4())},
        {"cues": [{"start_frame": 0, "end_frame": 24, "prompt": "A bird calls"}]},
    ],
)
def test_effects_draft_cannot_invent_a_film_or_scene_timing(reference):
    proposal = Proposal(
        name="Film sound",
        goal="Add film sounds",
        tools=["create_media"],
        media={"kind": "effects", "request": {"prompt": "Wind in trees", **reference}},
    )
    with pytest.raises(ValueError, match="Do not invent"):
        definition(proposal, "Create an agent that adds sound to a film", "fake-local")


@pytest.mark.parametrize(
    "model_schedule", [{"trigger": "manual"}, {"trigger": "cron", "cron_expr": "0 9 * * *"}]
)
def test_polish_quarter_hour_media_draft_keeps_cadence_and_enables_without_generating(
    model, implemented_media, model_schedule, monkeypatch
):
    from app.runner_client import RunnerClient

    def profile(_self, method, path, **_kwargs):
        assert (method, path) == ("GET", "/v1/photo/capabilities")
        return {"available": True, "modes": ["t2i"]}

    monkeypatch.setattr(RunnerClient, "request", profile)
    _, responses = model
    responses[:] = [
        json.dumps(
            {
                "name": "Mountain illustration",
                "goal": "Generate a peaceful mountain illustration",
                "tools": ["create_media"],
                "media": {
                    "kind": "image",
                    "request": {"mode": "t2i", "prompt": "Peaceful mountain illustration"},
                },
                **model_schedule,
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(
            api, instruction="Co 15 minut generuj mi zdjęcie gór.", schedule_timezone="Europe/Warsaw"
        )
        assert step() == run["id"]
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["trigger"] == "cron" and agent["cron_expr"] == "*/15 * * * *"
        assert agent["schedule_timezone"] == "Europe/Warsaw" and not agent["enabled"]
        enabled = api.post(
            "/api/agents/" + agent["id"] + "/enabled",
            json={"expected_updated_at": agent["updated_at"], "enabled": True},
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["next_run_at"] and enabled.json()["enabled"]
        with session_factory()() as session:
            # Activation must not silently enqueue or execute image generation.
            assert len(list(session.scalars(select(Run)))) == 1


@pytest.mark.parametrize(
    "instruction,expected",
    [
        ("Co 15 minut generuj mi zdjęcie gór.", "qwen"),
        ("Generate a mountain illustration using Qwen.", "qwen"),
        ("Generate a mountain illustration using Juggernaut XL.", "juggernaut"),
    ],
)
def test_image_draft_uses_qwen_by_default_and_retains_explicit_model(
    instruction, expected, implemented_media
):
    proposed = Proposal.model_validate(
        {
            "name": "Mountains",
            "goal": "Create a mountain illustration",
            "tools": ["create_media"],
            "media": {
                "kind": "image",
                "request": {
                    "mode": "t2i",
                    "backend": "juggernaut",
                    "prompt": "Calm mountains",
                    "seed": 123,
                    "negative": "blur, noise",
                },
            },
        }
    )
    saved = definition(proposed, instruction, "fake-local")
    assert saved.media.request.backend == expected
    assert not saved.enabled
    if expected == "qwen":
        assert saved.media.request.seed is None and saved.media.request.negative is None
    else:
        assert saved.media.request.seed == 123 and saved.media.request.negative == "blur, noise"
    assert saved.media.request.prompt == "Calm mountains"


def test_explicit_juggernaut_choice_can_replace_model_proposed_qwen(implemented_media):
    proposed = Proposal.model_validate(
        {
            "name": "Mountains",
            "goal": "Create an illustration",
            "tools": ["create_media"],
            "media": {
                "kind": "image",
                "request": {"mode": "t2i", "backend": "qwen", "prompt": "Calm mountains"},
            },
        }
    )
    saved = definition(proposed, "Create an image with JuggernautXL.", "fake-local")
    assert saved.media.request.backend == "juggernaut" and saved.media.request.seed == 42


def test_existing_image_agent_can_save_a_clean_qwen_switch_without_weakening_validation():
    with TestClient(app) as api:
        body = {
            "name": "Existing image policy",
            "goal": "Illustrate a neutral landscape",
            "model": "fake-local",
            "tools": ["create_media"],
            "media": {
                "kind": "image",
                "request": {
                    "mode": "t2i",
                    "backend": "juggernaut",
                    "prompt": "A mountain landscape",
                    "seed": 123,
                    "negative": "blur",
                },
            },
        }
        created = api.post("/api/agents", json=body)
        assert created.status_code == 201, created.text
        row = created.json()
        invalid = {
            **body,
            "expected_updated_at": row["updated_at"],
            "media": {"kind": "image", "request": {**body["media"]["request"], "backend": "qwen"}},
        }
        assert api.put("/api/agents/" + row["id"], json=invalid).status_code == 422
        clean = {
            **invalid,
            "media": {
                "kind": "image",
                "request": {**invalid["media"]["request"], "seed": None, "negative": None},
            },
        }
        saved = api.put("/api/agents/" + row["id"], json=clean)
        assert saved.status_code == 200, saved.text
        assert saved.json()["media"]["request"]["backend"] == "qwen"
        assert (
            saved.json()["media"]["request"]["seed"] is None
            and saved.json()["media"]["request"]["negative"] is None
        )
