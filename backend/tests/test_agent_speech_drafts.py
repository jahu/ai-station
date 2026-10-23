import json
from uuid import uuid4

import pytest
from app.agent_drafts import Proposal, available_media_outputs, definition
from app.api import app
from app.db import session_factory
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_drafts import model as model
from test_agent_drafts import state, step, submit
from test_agent_speech import speech_enabled as speech_enabled


def test_natural_speech_draft_waits_for_reviewed_voice_and_never_generates(model, speech_enabled):
    calls, responses = model
    responses[:] = [
        json.dumps(
            {
                "name": "Poranny komunikat",
                "goal": "Przygotuj i przeczytaj polskie powitanie",
                "tools": ["create_media"],
                "trigger": "cron",
                "cron_expr": "0 8 * * *",
                "media": {
                    "kind": "speech",
                    "description_source": "goal",
                    "request": {"text": "Krótkie polskie powitanie", "reference_artifact_id": None},
                },
            }
        )
    ]
    with TestClient(app) as api:
        queued = submit(api, instruction="Stwórz agenta z polskim powitaniem codziennie o08:00 UTC")
        step()
        done = state(api, queued)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert not agent["enabled"] and agent["next_run_at"] is None
        assert (
            agent["media"]["kind"] == "speech" and agent["media"]["request"]["reference_artifact_id"] is None
        )
        assert agent["model"] == "fake-local" and agent["cron_expr"] == "0 8 * * *"
        prompt = json.loads(calls[0]["messages"][1]["content"])
        assert "speech" in prompt["available_media_outputs"]
        with session_factory()() as s:
            assert [r.executor_type for r in s.scalars(select(Run))] == ["agent_draft"]
        response = api.post(
            "/api/agents/" + agent["id"] + "/enabled",
            json={"enabled": True, "expected_updated_at": agent["updated_at"]},
        )
        assert response.status_code == 422 and "voice reference" in response.text


def test_model_cannot_invent_a_voice_reference_in_a_disabled_proposal(speech_enabled):
    with pytest.raises(ValueError, match="Do not invent"):
        definition(
            Proposal(
                name="Speech",
                goal="Hello",
                tools=["create_media"],
                media={"kind": "speech", "request": {"text": "Hello", "reference_artifact_id": str(uuid4())}},
            ),
            "Use a voice",
            "fake-local",
        )


def test_unfinished_speech_is_not_in_the_draft_catalog(monkeypatch):
    from app import agent_media

    monkeypatch.setattr(agent_media, "SPEECH_AGENTS_ENABLED", False)
    assert available_media_outputs() == ["image", "music"]
