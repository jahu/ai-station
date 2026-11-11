"""Closed source references and deterministic editorial timing, without inference."""

from copy import deepcopy
from uuid import uuid4

import pytest
from app.studio_schema import Storyboard
from app.studio_storyboard import fit_timing, source_end_seconds, visual_origin
from pydantic import ValidationError
from test_studio_materials import board


def visual(length=120, kind="image", **extra):
    return {
        "purpose": "Show a useful detail",
        "duration_frames": length,
        "visual_kind": kind,
        "visual_brief": "A precisely lit glass prism",
        **extra,
    }


def shared(source, length=120, **extra):
    return {
        "purpose": "Another beat using the same source",
        "duration_frames": length,
        "visual_kind": "reuse",
        "reuse_scene": source,
        **extra,
    }


def test_shared_visual_chain_is_explicit_and_does_not_mint_artifact_authority():
    plan = Storyboard.model_validate(board("silent", scenes=[visual(), shared(0), shared(1)]))
    assert [visual_origin(plan, i) for i in range(3)] == [0, 0, 0]
    assert plan.scenes[2].source_artifact_id is None and plan.scenes[2].reference_artifact_ids == []
    legacy = Storyboard.model_validate(board("silent", scenes=[visual()])).model_dump(mode="json")
    assert "reuse_scene" not in legacy["scenes"][0]


@pytest.mark.parametrize(
    "scenes",
    [
        [shared(0)],
        [visual(), shared(1)],
        [visual(), shared(2)],
        [visual(), shared(-1)],
        [visual(), shared(True)],
        [visual(reuse_scene=0)],
        [visual(kind="graphics", layout="title", title="A title"), shared(0)],
        [visual(), shared(0, source_artifact_id=str(uuid4()))],
        [visual(), shared(0, reference_artifact_ids=[str(uuid4())])],
    ],
)
def test_invalid_or_forward_sources_and_competing_coordinates_are_rejected(scenes):
    with pytest.raises(ValidationError):
        Storyboard.model_validate(board("silent", scenes=scenes))


@pytest.mark.parametrize("durations,expected", [([240, 240], [120, 120]), ([120, 120, 120], [80, 80, 80])])
def test_actual_failure_shapes_fit_exact_eight_second_budget_without_mutation(durations, expected):
    plan = Storyboard.model_validate(board("silent", scenes=[visual(n) for n in durations]))
    original = deepcopy(plan.model_dump())
    fitted = fit_timing(plan, 8)
    assert fitted.frames == 240
    assert [s.duration_frames for s in fitted.scenes] == expected
    assert plan.model_dump() == original
    assert all(a.visual_brief == b.visual_brief for a, b in zip(plan.scenes, fitted.scenes, strict=True))


def test_remainder_frames_are_deterministic_and_never_drop_beats():
    plan = Storyboard.model_validate(board("silent", scenes=[visual(33), shared(0, 333), shared(1, 77)]))
    first, second = fit_timing(plan, 5), fit_timing(plan, 5)
    assert first.frames == second.frames == 150
    assert first.model_dump() == second.model_dump()
    assert len(first.scenes) == 3 and all(s.duration_frames >= 30 for s in first.scenes)
    assert first.scenes[2].reuse_scene == 1
    with pytest.raises(ValueError, match="fewer scenes"):
        fit_timing(Storyboard.model_validate(board("silent", scenes=[visual(30) for _ in range(6)])), 5)
    with pytest.raises(ValueError, match="more scenes"):
        fit_timing(Storyboard.model_validate(board("silent", scenes=[visual()])), 600)


def test_clip_coverage_includes_every_shared_trim_window_not_only_the_first_beat():
    plan = Storyboard.model_validate(
        board(
            "silent",
            scenes=[
                visual(60, kind="video"),
                shared(0, 120, media_start_seconds=4.0),
                shared(1, 30, media_start_seconds=2.5),
                visual(),
            ],
        )
    )
    assert source_end_seconds(plan, 0) == source_end_seconds(plan, 2) == 8
    assert source_end_seconds(plan, 3) == 4
