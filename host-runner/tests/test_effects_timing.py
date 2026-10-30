import pytest
from ai_station_runner.effects_timing import effects_windows


@pytest.mark.parametrize("fps", [24, 25])
@pytest.mark.parametrize("seconds,extra_frames", [(0, 1), (1, 0), (8, 0), (8, 1), (15, 0), (299, 1)])
def test_sound_windows_cover_every_source_frame_and_sample_without_rounding_drift(fps, seconds, extra_frames):
    frames = fps * seconds + extra_frames
    windows = effects_windows(frames, fps)
    assert windows[0].first_frame == windows[0].first_sample == 0
    assert windows[-1].first_frame + windows[-1].frames == frames
    assert windows[-1].end_sample == frames * 44100 // fps
    assert all(fps <= item.conditioning_frames <= fps * 8 for item in windows)
    assert all(item.frames <= item.conditioning_frames for item in windows)
    actual_samples = sum(w.end_sample - w.first_sample - w.overlap_samples for w in windows)
    assert actual_samples == frames * 44100 // fps
    for previous, current in zip(windows, windows[1:]):
        assert current.first_frame < previous.first_frame + previous.frames
        assert current.first_frame + current.frames > previous.first_frame + previous.frames
        assert current.overlap_samples == previous.end_sample - current.first_sample


def test_half_sample_frame_boundary_does_not_accumulate_per_window_rounding():
    windows = effects_windows(24 * 300 - 1, 24)
    assert windows[-1].end_sample == 13228162
    assert len(windows) < 45


@pytest.mark.parametrize(
    "frames,fps", [(0, 24), (-1, 24), (True, 24), (1, True), (1, 0), (1, 30), (7201, 24), (7501, 25)]
)
def test_invalid_or_unbounded_film_timing_is_rejected(frames, fps):
    with pytest.raises(ValueError):
        effects_windows(frames, fps)
