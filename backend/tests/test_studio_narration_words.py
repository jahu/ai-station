"""Spoken limits survive semantic selection and fail before expensive generation."""

import json
from uuid import uuid4

import pytest
from app.api import app
from app.studio_assistant_contract import StudioIntent, selected_context
from app.studio_schema import NarrationWords, Storyboard, StudioOptions, narration_word_count
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_studio_director import local_model, request, step  # noqa: F401
from test_studio_materials import board, material


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"minimum": 0},
        {"minimum": True},
        {"maximum": 1.5},
        {"maximum": 3001},
        {"minimum": 10, "maximum": 9},
    ],
)
def test_invalid_spoken_limits_are_rejected(value):
    with pytest.raises(ValidationError):
        NarrationWords.model_validate(value)


@pytest.mark.parametrize("limits", [{"minimum": 10}, {"maximum": 20}, {"minimum": 15, "maximum": 15}])
def test_semantic_limits_are_frozen_without_changing_brand_defaults(limits):
    intent = StudioIntent(audio="voice_music", narration_words=limits)
    assert selected_context(None, {}, intent)["options"]["narration_words"] == limits
    with pytest.raises(ValidationError):
        StudioOptions(audio="music", narration_words=limits)
    with pytest.raises(ValidationError):
        StudioIntent(audio="silent", narration_words=limits)


def test_no_limits_preserves_legacy_options_and_allows_sparse_narration():
    assert StudioOptions().model_dump() == {
        "format": "reel",
        "aspect": "portrait",
        "duration_seconds": 30,
        "audio": "voice_music",
    }
    assert "narration_words" not in StudioIntent().model_dump()
    assert "narration_words" not in selected_context(None, {}, StudioIntent())["options"]
    assert narration_word_count(Storyboard.model_validate(board())) == 8


def test_word_count_uses_only_spoken_words_across_scenes():
    data = board()
    data["scenes"][0]["narration"] = "Zażółć — gęślą.\nAI-powered 2026!"
    data["scenes"][0]["title"] = "This title must not count"
    data["scenes"].append({**data["scenes"][0], "narration": "Two more."})
    assert narration_word_count(Storyboard.model_validate(data)) == 6


@pytest.mark.parametrize("limits", [{"minimum": 10}, {"maximum": 2}, {"minimum": 12, "maximum": 12}])
def test_director_repairs_only_spoken_script_before_publication(local_model, limits):  # noqa: F811
    calls, responses = local_model
    good = board()
    count = limits.get("minimum", limits.get("maximum"))
    good["scenes"][0]["narration"] = " ".join(["word"] * count)
    responses[:] = [json.dumps(board()), json.dumps(good)]
    with TestClient(app) as browser:
        created = material(browser, options={"audio": "voice_music", "narration_words": limits})
        path = "/api/studio/materials/" + created["id"]
        queued = browser.post(path + "/plan", json=request()).json()
        step()
        done = browser.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        assert len(calls) == 2 and "8 spoken words" in calls[1]["messages"][-1]["content"]
        revisions = browser.get(path + "/revisions").json()
        assert len(revisions) == 1 and revisions[0]["options"]["narration_words"] == limits
        assert narration_word_count(Storyboard.model_validate(revisions[0]["storyboard"])) == count
        assert done["parameters"]["frozen"]["options"]["narration_words"] == limits


def test_unsatisfied_limits_fail_without_overwriting_previous_version(local_model):  # noqa: F811
    calls, _ = local_model
    with TestClient(app) as browser:
        created = material(browser, options={"narration_words": {"minimum": 8, "maximum": 8}})
        path = "/api/studio/materials/" + created["id"]
        saved = browser.post(
            path + "/revisions",
            json={"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": board()},
        ).json()
        # Settings govern new versions; the old revision remains immutable.
        changed = browser.patch(
            path, json={"expected_version": 2, "options": {"narration_words": {"minimum": 20}}}
        )
        assert changed.status_code == 200, changed.text
        queued = browser.post(
            path + "/plan", json=request(expected_version=3, parent_revision_id=saved["id"])
        ).json()
        step()
        done = browser.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "failed" and "at least 20" in done["error_message"]
        assert len(calls) == 2 and browser.get(path + "/revisions").json() == [saved]
        assert not browser.get("/api/artifacts?run_id=" + queued["id"]).json()


def test_manual_save_cannot_mislabel_script_as_meeting_word_limits():
    with TestClient(app) as browser:
        created = material(browser, options={"narration_words": {"minimum": 20}})
        response = browser.post(
            "/api/studio/materials/" + created["id"] + "/revisions",
            json={"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": board()},
        )
        assert response.status_code == 422 and "at least 20" in response.text
        assert browser.get("/api/studio/materials/" + created["id"] + "/revisions").json() == []
