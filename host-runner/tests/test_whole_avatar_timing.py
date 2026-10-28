from fractions import Fraction

import pytest
from ai_station_runner.whole_avatar_timing import WholeAvatarTiming, portrait_canvas


@pytest.mark.parametrize(
    "samples,rate,frames,base,endpoint",
    [
        (961920, 24000, 1002, 501, 1),
        (24000, 24000, 25, 13, 0),
        (24001, 24000, 26, 13, 1),
        (5440, 8000, 17, 9, 0),
        (5760000, 96000, 1500, 750, 1),
    ],
)
def test_preserves_complete_speech_with_exact_odd_even_endpoint_timing(samples, rate, frames, base, endpoint):
    timing = WholeAvatarTiming(samples, rate)
    assert timing.target_frames == frames
    assert timing.base_frames == base
    assert timing.feature_frames == 2 * base
    assert timing.endpoint_frames == endpoint
    assert 2 * base - 1 + endpoint == frames
    duration = Fraction(samples, rate)
    assert 0 <= Fraction(frames, 25) - duration < Fraction(1, 25)
    assert Fraction(frames - 1, 25) < duration


@pytest.mark.parametrize("rate", [8000, 16000, 22050, 24000, 44100, 48000, 96000])
def test_non_integral_audio_lengths_do_not_accumulate_rounding_loss(rate):
    for samples in [rate + 1, 17 * rate + 13, 60 * rate - 1]:
        timing = WholeAvatarTiming(samples, rate)
        assert timing.target_frames * rate >= samples * 25
        assert (timing.target_frames - 1) * rate < samples * 25
        assert timing.endpoint_frames in (0, 1)
        assert timing.feature_frames >= timing.target_frames


@pytest.mark.parametrize(
    "samples,rate",
    [
        (True, 24000),
        (24000, True),
        (24000.0, 24000),
        (24000, 24000.0),
        (0, 24000),
        (-1, 24000),
        (5439, 8000),
        (5760001, 96000),
        (24000, 7999),
        (24000, 96001),
        ("24000", 24000),
    ],
)
def test_rejects_invalid_or_out_of_profile_canonical_audio(samples, rate):
    with pytest.raises(ValueError):
        WholeAvatarTiming(samples, rate)


@pytest.mark.parametrize(
    "width,height,expected",
    [
        (1024, 1536, (256, 384)),
        (1536, 1024, (384, 256)),
        (8192, 2048, (384, 128)),
        (2048, 8192, (128, 384)),
        (1024, 1024, (384, 384)),
        (32, 32, (384, 384)),
        (1000, 1333, (320, 384)),
    ],
)
def test_canvas_bounds_upstream_shortest_side_scaling_without_cropping(width, height, expected):
    canvas = portrait_canvas(width, height)
    assert canvas == expected
    assert max(canvas) == 384
    assert all(side % 64 == 0 for side in canvas)
    scale = Fraction(384, max(width, height))
    assert Fraction(width) * scale <= canvas[0]
    assert Fraction(height) * scale <= canvas[1]


@pytest.mark.parametrize(
    "width,height",
    [
        (True, 384),
        (384, False),
        (384.0, 384),
        (384, "384"),
        (31, 384),
        (8193, 8193),
        (32, 129),
        (129, 32),
        (0, 0),
        (-384, 384),
    ],
)
def test_canvas_rejects_unsupported_or_noninteger_source_geometry(width, height):
    with pytest.raises(ValueError):
        portrait_canvas(width, height)
