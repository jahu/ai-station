"""Measured speech may consume still holds, never words or selected clip windows."""

import random
from copy import deepcopy
from uuid import uuid4

import pytest
from app.studio_audio_production import ProduceAudio
from app.studio_pcm import timed_storyboard
from app.studio_production import Produce
from app.studio_schema import Storyboard
from app.studio_soundtrack import MixRequest


def plan(lengths, voiced=(0,), kinds=None):
    scenes = []
    for index, length in enumerate(lengths):
        kind = kinds[index] if kinds else "image"
        scenes.append(
            {
                "purpose": f"Beat {index}",
                "duration_frames": length,
                "visual_kind": kind,
                "visual_brief": "An original visual explanation",
                "narration": "A complete spoken cue." if index in voiced else "",
                **({"source_artifact_id": str(uuid4())} if kind == "library" else {}),
            }
        )
    return Storyboard.model_validate(
        {
            "title": "Measured edit",
            "concept": "A complete thought",
            "hook": "Look closer",
            "audio": "voice",
            "scenes": scenes,
        }
    )


def cue(frames, extra_samples=0):
    return {"samples": frames * 1600 + extra_samples, "sample_rate": 48000}


def test_actual_305_frame_cue_fits_12_seconds_without_rewriting_script_or_sources():
    original = plan([180, 180], kinds=["library", "library"])
    sources = {str(s.source_artifact_id): {"kind": "image"} for s in original.scenes}
    frozen = deepcopy(original.model_dump())
    voices = {0: cue(293)}
    assert timed_storyboard(original, voices).frames == 485
    assert timed_storyboard(original, voices, policy="preserve").frames == 485
    fitted = timed_storyboard(original, voices, policy="fit", sources=sources)
    assert [s.duration_frames for s in fitted.scenes] == [305, 55]
    assert timed_storyboard(fitted, voices, policy="fit", sources=sources) == fitted
    assert original.model_dump() == frozen
    for old, new in zip(original.scenes, fitted.scenes, strict=True):
        assert old.model_dump(exclude={"duration_frames"}) == new.model_dump(exclude={"duration_frames"})


def test_fractional_spoken_tail_and_cue_margins_are_lower_bounds():
    fitted = timed_storyboard(plan([180, 180]), {0: cue(293, 1)}, policy="fit")
    assert [s.duration_frames for s in fitted.scenes] == [306, 54]
    impossible = timed_storyboard(plan([180, 180], voiced=(0, 1)), {0: cue(240), 1: cue(240)}, policy="fit")
    assert impossible.frames == 504 and all(s.duration_frames == 252 for s in impossible.scenes)


def test_generated_footage_can_grow_for_its_words_but_selected_library_windows_stay_fixed():
    fitted = timed_storyboard(plan([120, 240], kinds=["video", "image"]), {0: cue(180)}, policy="fit")
    assert [s.duration_frames for s in fitted.scenes] == [192, 168]
    selected = plan([120, 240], kinds=["library", "image"])
    sources = {str(selected.scenes[0].source_artifact_id): {"kind": "video"}}
    with pytest.raises(ValueError, match="planned Library window"):
        timed_storyboard(selected, {0: cue(109)}, policy="fit", sources=sources)
    assert [
        s.duration_frames
        for s in timed_storyboard(selected, {0: cue(100)}, policy="fit", sources=sources).scenes
    ] == [120, 240]


def test_shared_images_remain_shared_and_unknown_library_types_are_conservative():
    original = plan([180, 180])
    original.scenes[1] = original.scenes[1].model_copy(update={"visual_kind": "reuse", "reuse_scene": 0})
    fitted = timed_storyboard(original, {0: cue(293)}, policy="fit")
    assert fitted.frames == 360 and fitted.scenes[1].reuse_scene == 0
    unknown = plan([180, 180], voiced=(1,), kinds=["library", "image"])
    fitted = timed_storyboard(unknown, {1: cue(293)}, policy="fit")
    assert [s.duration_frames for s in fitted.scenes] == [180, 305]


def test_finite_scene_and_total_limits_cannot_be_bypassed_with_long_speech():
    with pytest.raises(ValueError, match="ninety-second"):
        timed_storyboard(plan([30]), {0: cue(2700)}, policy="fit")
    with pytest.raises(ValueError, match="ten-minute"):
        timed_storyboard(plan([30] * 8, voiced=range(8)), {i: cue(2500) for i in range(8)}, policy="fit")


def test_rounding_honors_all_real_cues_and_keeps_unchanged_edits_stable():
    rng = random.Random(752)
    for _ in range(60):
        count = rng.randint(2, 8)
        original = plan([rng.randint(30, 800) for _ in range(count)], voiced=range(count))
        voices = {i: cue(rng.randint(1, 800), rng.randint(0, 1)) for i in range(count)}
        floors = [max(30, (v["samples"] + 1599) // 1600 + 12) for v in voices.values()]
        fitted = timed_storyboard(original, voices, policy="fit")
        assert fitted.frames == max(original.frames, sum(floors))
        assert all(s.duration_frames >= floors[i] for i, s in enumerate(fitted.scenes))
        assert timed_storyboard(fitted, voices, policy="fit") == fitted


@pytest.mark.parametrize("request_type", [MixRequest, ProduceAudio, Produce])
def test_old_request_serialization_omits_policy_and_rejects_unknown_strategies(request_type):
    values = {"client_request_id": uuid4(), "revision_id": uuid4()}
    assert "timing_policy" not in request_type(**values).model_dump(mode="json")
    assert request_type(**values, timing_policy="fit").model_dump(mode="json")["timing_policy"] == "fit"
    with pytest.raises(ValueError):
        request_type(**values, timing_policy="truncate_audio")
