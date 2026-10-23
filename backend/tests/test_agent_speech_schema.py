from uuid import uuid4

import pytest
from app.agent_schema import AgentSettings
from app.api import app
from app.audio import SpeechRequest
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_ordinary_speech_still_requires_a_reference_and_rejects_internal_budgets():
    with pytest.raises(ValidationError):
        SpeechRequest(text="Hello")
    with pytest.raises(ValidationError):
        SpeechRequest(text="Hello", reference_artifact_id=uuid4(), execution_deadline_at="2026-10-23")


def test_disabled_speech_scope_round_trips_without_inventing_a_voice_or_enabling_execution():
    with TestClient(app) as api:
        response = api.post(
            "/api/agents",
            json={
                "name": "Daily spoken brief",
                "goal": "Read a short Polish summary",
                "tools": ["create_media"],
                "media": {
                    "kind": "speech",
                    "description_source": "goal",
                    "request": {"text": "A short Polish briefing"},
                },
            },
        )
        assert response.status_code == 201, response.text
        agent = response.json()
        assert not agent["enabled"] and agent["media"]["request"]["reference_artifact_id"] is None
        response = api.post(
            "/api/agents/" + agent["id"] + "/enabled",
            json={"enabled": True, "expected_updated_at": agent["updated_at"]},
        )
        assert response.status_code == 422 and "voice reference" in response.text
        assert api.get("/api/runs").json() == []


def test_reviewed_voice_cannot_enable_unfinished_speech_execution():
    with TestClient(app) as api:
        response = api.post(
            "/api/agents",
            json={
                "name": "Spoken brief",
                "goal": "Read a short Polish summary",
                "enabled": True,
                "tools": ["create_media"],
                "media": {
                    "kind": "speech",
                    "request": {"text": "Hello", "reference_artifact_id": str(uuid4())},
                },
            },
        )
        assert response.status_code == 409 and "not available yet" in response.text
        assert api.get("/api/runs").json() == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference_path", "/home/private/voice.wav"),
        ("model_url", "https://example.com/voice"),
        ("permissions", ["external_ai"]),
    ],
)
def test_speech_scope_cannot_inject_paths_models_or_permissions(field, value):
    with pytest.raises(ValidationError):
        AgentSettings(
            name="Speech",
            goal="Read",
            tools=["create_media"],
            media={
                "kind": "speech",
                "request": {"text": "Hello", field: value},
            },
        )
