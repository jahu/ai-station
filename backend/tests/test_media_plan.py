import pytest
from app.media_plan import audio_boundary, audio_frames, duration_frames, timeline


@pytest.mark.parametrize("seconds,fps", [(15, 24), (30, 24), (60, 24), ("15.25", 24), ("0.68", 25)])
def test_timeline_covers_every_requested_frame_with_valid_native_windows(seconds, fps):
    plan = timeline(frames=duration_frames(seconds, fps), fps=fps, seed=42)
    assert sum(s.output_frames for s in plan.segments) == plan.target_frames
    assert all(
        s.generated_frames in (17, 33, 49, 65, 81) and s.output_frames <= s.generated_frames
        for s in plan.segments
    )
    assert plan == timeline(frames=plan.target_frames, fps=fps, seed=42)
    assert len({s.seed for s in plan.segments}) == len(plan.segments)


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
