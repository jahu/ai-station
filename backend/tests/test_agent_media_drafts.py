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


@pytest.mark.parametrize("kind", ["image", "music", "video"])
def test_media_draft_publishes_disabled_settings_without_generation(model, implemented_media, kind):
    calls, responses = model
    request = {
        "image": {"mode": "t2i", "prompt": "New forest illustration"},
        "music": {"caption": "Calm piano", "duration_seconds": 60},
        "video": {"prompt": "Quiet forest film", "duration_seconds": 30},
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
