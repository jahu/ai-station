"""Complete-frame and native conditioning handoff without any model dependencies."""

import pytest
from ai_station_runner.sonic_frames import capture_inputs, recording_frames
from ai_station_runner.whole_avatar_timing import WholeAvatarTiming


def test_preparation_retains_the_exact_arguments_and_never_normalizes_a_dummy_movie():
    image, audio = object(), object()

    def native(proxy, configuration, batch):
        assert configuration == "fixed" and batch == "intact"
        proxy(image, audio, num_frames=501, frames_per_batch=25, overlap=0)
        pytest.fail("Native postprocessing must not run or create a dummy full movie")

    args, kwargs = capture_inputs(native, "allocated", "fixed", "intact")
    assert args == (image, audio)
    assert kwargs == {"num_frames": 501, "frames_per_batch": 25, "overlap": 0}


def test_unrelated_preparation_failure_is_never_mistaken_for_ready_inputs():
    def native(proxy):
        raise RuntimeError("No face detected")

    with pytest.raises(RuntimeError, match="No face"):
        capture_inputs(native, "allocated")
    with pytest.raises(ValueError, match="expected pipeline"):
        capture_inputs(lambda proxy: None, "allocated")


@pytest.mark.parametrize(
    "samples, expected",
    [
        (16320, [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8]),
        (16321, [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8]),
    ],
)
def test_endpoint_is_derived_from_audio_samples_and_no_internal_frame_is_repeated(samples, expected):
    timing = WholeAvatarTiming(samples, 24000)
    observed = list(recording_frames(iter(range(9)), timing, lambda a, b: (a + b) / 2))
    assert observed == expected and len(observed) == timing.target_frames


@pytest.mark.parametrize("frames", [[], list(range(8)), list(range(10)), [*range(9), None]])
def test_missing_or_extra_frames_cannot_be_published_as_a_complete_recording(frames):
    with pytest.raises(ValueError):
        list(recording_frames(frames, WholeAvatarTiming(16320, 24000), lambda a, b: (a + b) / 2))


def test_interpolation_stream_does_not_eagerly_materialize_the_whole_movie():
    consumed = []

    def base():
        for index in range(501):
            consumed.append(index)
            yield index

    stream = recording_frames(base(), WholeAvatarTiming(961920, 24000), lambda a, b: (a + b) / 2)
    assert consumed == []
    assert next(stream) == 0 and consumed == [0]
    assert next(stream) == 0.5 and consumed == [0, 1]
    assert next(stream) == 1 and consumed == [0, 1]
    assert len(list(stream)) == 999 and len(consumed) == 501
