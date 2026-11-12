"""Clean spoken words and optional Fish performance hints stay separate."""

import json
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.studio_audio_production import Voice
from app.studio_narration_edit import apply_edit
from app.studio_schema import Storyboard, narration_word_count
from fastapi.testclient import TestClient
from test_studio_audio_production import generators, submit  # noqa: F401
from test_studio_materials import board
from test_studio_render import draft


def expressive():
    value = board()
    value["scenes"][0]["narration_segments"] = [
        {"text": "A small change", "style": "curious and engaging"},
        {"text": "can reveal a hidden pattern.", "style": "warm and confident"},
    ]
    return value


def test_phrase_hints_compile_for_fish_without_changing_words_or_legacy_identity():
    legacy = Storyboard.model_validate(board())
    assert "narration_segments" not in legacy.scenes[0].model_dump(mode="json")
    plan = Storyboard.model_validate(expressive())
    shot = plan.scenes[0]
    assert narration_word_count(plan) == narration_word_count(legacy) == 8
    assert Voice().request(shot.narration, None, segments=shot.narration_segments).text == (
        "[curious and engaging] A small change [warm and confident] can reveal a hidden pattern."
    )
    assert (
        Voice(direction="whisper").request(shot.narration, None, segments=shot.narration_segments).text
        == shot.narration
    )
    reference = uuid4()
    plain = Voice(engine="chatterbox", reference_artifact_id=reference)
    assert plain.request(shot.narration, reference, segments=shot.narration_segments).text == shot.narration


@pytest.mark.parametrize(
    "segments",
    [
        [],
        [{"text": "Invented words", "style": "happy"}],
        [{"text": "A small change can reveal a hidden pattern.", "style": "warm]\n[angry"}],
        [{"text": "A small change can reveal a hidden pattern.", "style": "x" * 121}],
        [{"text": " ", "style": "happy"}],
        [{"text": "A small change can reveal a hidden pattern."}] * 13,
    ],
)
def test_invalid_phrase_maps_fail_before_any_generation(segments):
    value = board()
    value["scenes"][0]["narration_segments"] = segments
    with pytest.raises(ValueError):
        Storyboard.model_validate(value)


def test_whitespace_is_allowed_but_punctuation_and_speech_budget_remain_exact():
    value = expressive()
    value["scenes"][0]["narration_segments"][0]["text"] = "  A   small change\n"
    assert Storyboard.model_validate(value)
    value["scenes"][0]["narration_segments"][1]["text"] = "can reveal a hidden pattern!"
    with pytest.raises(ValueError, match="every spoken word"):
        Storyboard.model_validate(value)
    value = board()
    value["scenes"][0].update(narration="a" * 999, narration_segments=[{"text": "a" * 999, "style": "warm"}])
    with pytest.raises(ValueError, match="1000 characters"):
        Storyboard.model_validate(value)


def test_rewriting_words_clears_only_stale_phrase_hints_and_keeps_visuals():
    plan = Storyboard.model_validate(expressive())
    untouched = apply_edit(plan, json.dumps({"lines": [{"scene": 0, "text": plan.scenes[0].narration}]}), {})
    assert untouched.model_dump() == plan.model_dump()
    edited = apply_edit(plan, json.dumps({"lines": [{"scene": 0, "text": "Look a little closer."}]}), {})
    assert edited.scenes[0].narration_segments is None
    assert edited.scenes[0].visual_brief == plan.scenes[0].visual_brief
    assert plan.scenes[0].narration_segments is not None


def test_worker_uses_saved_expression_and_normal_delivery_without_mutating_revision(generators):  # noqa: F811
    speech, _, executors = generators
    with TestClient(app) as client:
        row, original = draft(client, audio="voice_music")
        updated = dict(original["storyboard"])
        updated["scenes"] = expressive()["scenes"]
        response = client.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": 2,
                "parent_revision_id": original["id"],
                "storyboard": updated,
            },
        )
        assert response.status_code == 201, response.text
        revision = response.json()
        queued = submit(client, row, revision)
        assert queued.status_code == 202, queued.text
        with session_factory()() as session:
            tick(session, "expression", executors=executors)
        assert len(speech) == 1
        assert speech[0]["text"].startswith("[curious and engaging]")
        assert speech[0]["pace"] == speech[0]["direction"] == "natural"
        saved = client.get(f"/api/studio/materials/{row['id']}/revisions").json()[0]
        assert saved == revision
