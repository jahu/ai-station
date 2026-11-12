"""Speech editing preserves visual intent and never relaxes publication validation."""

import json
from copy import deepcopy

import pytest
from app.studio_narration_edit import apply_edit, word_hints
from app.studio_schema import Storyboard
from app.studio_storyboard import fit_timing
from test_studio_materials import board


def plan():
    first = board()["scenes"][0]
    return Storyboard.model_validate(
        board(
            scenes=[
                {**first, "duration_frames": 120},
                {
                    **first,
                    "visual_kind": "image",
                    "duration_frames": 600,
                    "narration": "Another useful idea follows.",
                },
                {**first, "visual_kind": "reuse", "reuse_scene": 1, "duration_frames": 60, "narration": ""},
            ]
        )
    )


def test_indexed_edits_only_change_narration_and_keep_all_visual_and_audio_fields():
    original = plan()
    snapshot = original.model_dump(mode="json")
    # JSON order is not timeline authority; explicit original indices are.
    text = json.dumps(
        {
            "lines": [
                {"scene": 2, "text": ""},
                {"scene": 0, "text": "Light reveals a pattern."},
                {"scene": 1, "text": "Look closely to understand it."},
            ]
        }
    )
    edited = apply_edit(
        original, text, {"audio": "voice_music", "narration_words": {"minimum": 9, "maximum": 9}}
    )
    assert original.model_dump(mode="json") == snapshot
    expected = deepcopy(snapshot)
    expected["scenes"][0]["narration"] = "Light reveals a pattern."
    expected["scenes"][1]["narration"] = "Look closely to understand it."
    assert edited.model_dump(mode="json") == expected


@pytest.mark.parametrize(
    "lines",
    [
        [{"scene": 0, "text": "valid"}],
        [{"scene": 0, "text": "valid"}, {"scene": 0, "text": "again"}, {"scene": 2, "text": ""}],
        [{"scene": False, "text": "valid"}, {"scene": 1, "text": "valid"}, {"scene": 2, "text": ""}],
        [{"scene": 0, "text": ""}, {"scene": 1, "text": "valid"}, {"scene": 2, "text": ""}],
        [
            {"scene": 0, "text": "valid"},
            {"scene": 1, "text": "valid"},
            {"scene": 2, "text": "Invented speech"},
        ],
        [
            {"scene": 0, "text": "valid", "duration_frames": 60},
            {"scene": 1, "text": "valid"},
            {"scene": 2, "text": ""},
        ],
    ],
)
def test_missing_duplicate_coerced_indices_silence_changes_and_visual_edits_are_rejected(lines):
    with pytest.raises(ValueError):
        apply_edit(plan(), json.dumps({"lines": lines}), {"audio": "voice_music"})


def test_pacing_hints_retain_total_budget_and_leave_room_on_short_video_beats():
    fitted = fit_timing(plan(), 26)
    hints = word_hints(fitted, 60, {})
    assert set(hints) == {0, 1}
    assert sum(hints.values()) == 60
    assert hints[0] <= 7 and hints[1] > 50
    # Advice never changes or trims the original script or timeline.
    assert fitted == plan()
