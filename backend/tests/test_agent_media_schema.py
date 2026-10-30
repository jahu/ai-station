from uuid import uuid4

import pytest
from app.agent_media_schema import AgentImageScope, AgentMediaScope, AgentMusicScope
from pydantic import TypeAdapter, ValidationError

scope = TypeAdapter(AgentMediaScope)


def test_expressive_speech_agent_round_trip_keeps_direction_outside_spoken_words():
    value = {
        "kind": "speech",
        "description_source": "fixed",
        "request": {
            "text": "Dzień dobry. To są dokładne słowa.",
            "reference_artifact_id": str(uuid4()),
            "engine": "fish_s2_pro",
            "direction": "whisper",
            "pace": "slow",
        },
    }
    result = scope.validate_python(value)
    saved = result.model_dump(mode="json")
    assert saved["request"]["text"] == value["request"]["text"]
    assert saved["request"]["engine"] == "fish_s2_pro"
    assert saved["request"]["direction"] == "whisper"
    assert saved["request"]["pace"] == "slow"
    assert "delivery" not in saved["request"]
    assert scope.validate_python(saved).model_dump(mode="json") == saved


def test_image_scope_reuses_real_photo_modes_and_uuid_references():
    reference = uuid4()
    result = scope.validate_python(
        {
            "kind": "image",
            "request": {
                "mode": "recompose",
                "prompt": "Keep the person in a new setting",
                "input_artifact_ids": [str(reference)],
            },
        }
    )
    assert isinstance(result, AgentImageScope)
    assert result.request.input_artifact_ids == [reference]
    assert (result.request.width, result.request.height) == (832, 1216)


def test_music_scope_keeps_lyrics_and_resolves_no_seed_or_receipt_before_dispatch():
    result = scope.validate_python(
        {
            "kind": "music",
            "request": {
                "caption": "Acoustic folk",
                "instrumental": False,
                "lyrics": "[Verse]\nA quiet morning",
                "duration_seconds": 30,
            },
        }
    )
    assert isinstance(result, AgentMusicScope)
    assert result.request.lyrics == "[Verse]\nA quiet morning"
    assert result.request.seed is None
    assert "client_request_id" not in result.request.model_dump()


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "invented", "request": {}},
        {"kind": "image", "request": {"mode": "t2i", "prompt": "Photo", "command": "anything"}},
        {"kind": "image", "request": {"mode": "img2img", "edit_prompt": "New clothing"}},
        {
            "kind": "image",
            "request": {"mode": "upscale", "input_artifact_ids": ["/etc/passwd"]},
        },
        {"kind": "music", "request": {"caption": "Song", "instrumental": False}},
        {"kind": "music", "request": {"caption": "Piano", "duration_seconds": 601}},
        {"kind": "music", "request": {"caption": "Piano", "client_request_id": str(uuid4())}},
        {"kind": "music", "request": {"caption": "Piano", "model_url": "https://example.com/model"}},
        {"kind": "music", "request": {"caption": "Piano"}, "permissions": ["external_ai"]},
    ],
)
def test_media_scopes_do_not_accept_invented_inputs_or_authority(value):
    with pytest.raises(ValidationError):
        scope.validate_python(value)


def test_disabled_media_scope_round_trips_and_duplicates_without_an_installed_engine():
    from app.api import app
    from fastapi.testclient import TestClient

    with TestClient(app) as api:
        response = api.post(
            "/api/agents",
            json={
                "name": "Morning piano",
                "goal": "Create a calm instrumental",
                "model": "fake-local",
                "tools": ["create_media"],
                "media": {"kind": "music", "request": {"caption": "Calm piano"}},
            },
        )
        assert response.status_code == 201, response.text
        original = response.json()
        assert original["media"]["request"]["caption"] == "Calm piano"
        assert original["enabled"] is False
        copied = api.post(
            f"/api/agents/{original['id']}/duplicate",
            json={"expected_updated_at": original["updated_at"]},
        )
        assert copied.status_code == 201, copied.text
        assert copied.json()["media"] == original["media"]
        assert copied.json()["id"] != original["id"] and copied.json()["enabled"] is False
        enabled = api.post(
            f"/api/agents/{original['id']}/enabled",
            json={"expected_updated_at": original["updated_at"], "enabled": True},
        )
        assert enabled.status_code == 409 and "engine is unavailable" in enabled.text
        assert api.get("/api/runs").json() == []


def test_media_scope_cannot_be_attached_to_an_unrelated_agent():
    from app.agent_schema import AgentSettings

    with pytest.raises(ValidationError, match="require the Create media"):
        AgentSettings(
            name="Read only",
            goal="Inspect the workstation",
            tools=["system_snapshot"],
            media={"kind": "music", "request": {"caption": "Piano"}},
        )
    with pytest.raises(ValidationError, match="cannot inherit coding"):
        AgentSettings(
            name="Mixed authority",
            goal="Do unrelated things",
            tools=["coding_local", "create_media"],
            media={"kind": "music", "request": {"caption": "Piano"}},
        )


def test_nullable_media_migration_preserves_existing_agent_definition(legacy_schema):
    from alembic import command
    from app.api import app
    from app.db import alembic_config
    from fastapi.testclient import TestClient

    with TestClient(app) as api:
        original = api.post(
            "/api/agents", json={"name": "Legacy agent", "goal": "Keep this definition"}
        ).json()
        legacy_schema("0031")
        command.upgrade(alembic_config(), "head")
        restored = api.get("/api/agents/" + original["id"]).json()
        assert restored["media"] is None
        for key in ("id", "name", "goal", "enabled", "tools", "model", "created_at"):
            assert restored[key] == original[key]
