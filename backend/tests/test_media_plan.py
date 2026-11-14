import pytest
from app.media_plan import MediaTimeline, audio_boundary, audio_frames, duration_frames, timeline
from pydantic import ValidationError


@pytest.mark.parametrize(
    "seconds,fps", [(10, 15), (20, 15), (15, 24), (30, 24), (60, 24), ("15.25", 24), ("0.68", 25)]
)
def test_timeline_covers_every_requested_frame_with_valid_native_windows(seconds, fps):
    plan = timeline(frames=duration_frames(seconds, fps), fps=fps, seed=42)
    assert sum(s.output_frames for s in plan.segments) == plan.target_frames
    assert all(
        s.generated_frames in (17, 33, 49, 65, 81) and s.output_frames <= s.generated_frames
        for s in plan.segments
    )
    assert plan == timeline(frames=plan.target_frames, fps=fps, seed=42)
    assert len({s.seed for s in plan.segments}) == len(plan.segments)


@pytest.mark.parametrize("fps", [True, "15", 15.0, 14, 16, 23, 30])
def test_frozen_timeline_accepts_only_exact_supported_integer_frame_rates(fps):
    plan = timeline(frames=150, fps=15, seed=42)
    with pytest.raises(ValidationError):
        MediaTimeline.model_validate({**plan.model_dump(), "fps": fps})
    with pytest.raises(ValueError):
        timeline(frames=150, fps=fps, seed=42)


def test_full_audio_timing_uses_absolute_boundaries_without_drift():
    samples = 30 * 22050 + 11
    frames = audio_frames(samples, 22050)
    assert (frames - 1) * 22050 < samples * 25 <= frames * 22050
    plan = timeline(frames=frames, fps=25, seed=43)
    boundaries = [audio_boundary(s.start_frame, 22050) for s in plan.segments] + [samples]
    assert sum(b - a for a, b in zip(boundaries, boundaries[1:])) == samples
    assert frames / 25 - samples / 22050 < 1 / 25


def test_continuous_timeline_counts_only_new_motion_after_the_context_window():
    plan = timeline(frames=360, fps=24, seed=43, mode="continuous")
    assert plan.segments[0].first_frame == 0
    assert all(segment.first_frame == 17 for segment in plan.segments[1:])
    assert all(
        segment.first_frame + segment.output_frames <= segment.generated_frames for segment in plan.segments
    )
    assert sum(segment.output_frames for segment in plan.segments) == 360


def test_recurrent_timing_keeps_the_four_frame_prefix_and_exact_duration():
    plan = timeline(frames=150, fps=15, seed=43, mode="continuous", context_frames=4)
    assert [(part.first_frame, part.output_frames, part.generated_frames) for part in plan.segments] == [
        (0, 81, 81),
        (4, 69, 81),
    ]
    assert plan.target_frames / plan.fps == 10


@pytest.mark.parametrize("seconds", [1, 5, 10, 12, 20])
def test_fixed_window_recipe_never_shortens_native_sampling_for_a_trimmed_tail(seconds):
    plan = timeline(
        frames=seconds * 15, fps=15, seed=43, mode="continuous", context_frames=4, fixed_windows=True
    )
    assert all(part.generated_frames == 81 for part in plan.segments)
    assert sum(part.output_frames for part in plan.segments) == seconds * 15
    assert all(part.first_frame == 4 for part in plan.segments[1:])


@pytest.mark.parametrize("fixed", [1, None, "true"])
def test_fixed_window_policy_is_not_coerced(fixed):
    with pytest.raises(ValueError):
        timeline(frames=180, fps=15, seed=43, fixed_windows=fixed)


def test_recurrent_scene_windows_continue_inside_a_scene_and_reset_at_explicit_cuts():
    plan = timeline(
        frames=210,
        fps=15,
        seed=43,
        mode="shots",
        scene_frames=[90, 120],
        context_frames=4,
        fixed_windows=True,
        continue_within_scenes=True,
    )
    assert [part.first_frame for part in plan.segments] == [0, 4, 0, 4]
    assert [part.output_frames for part in plan.segments] == [81, 9, 81, 39]
    assert all(part.generated_frames == 81 for part in plan.segments)
    legacy = timeline(frames=210, fps=15, seed=43, mode="shots", scene_frames=[90, 120], context_frames=4)
    assert [part.first_frame for part in legacy.segments] == [0, 0, 0, 0]
    assert [part.generated_frames for part in legacy.segments] == [81, 17, 81, 49]


@pytest.mark.parametrize("policy", [1, None, "true"])
def test_scene_continuation_policy_is_not_coerced(policy):
    with pytest.raises(ValueError):
        timeline(
            frames=210, fps=15, seed=43, mode="shots", scene_frames=[90, 120], continue_within_scenes=policy
        )
