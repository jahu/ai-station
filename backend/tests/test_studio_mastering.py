"""Real CPU libav DSP over synthetic PCM; no models, network or hardware claims."""

import wave

import numpy as np
import pytest
from app.studio_mastering import MAX_GAIN_DB, PROFILE, master_wave, measure


def recording(path, amplitude=0.02, samples=240037, peak=False):
    times = np.arange(samples) / 48000
    values = np.repeat((amplitude * np.sin(times * 2 * np.pi * 440))[:, None], 2, axis=1)
    if peak:
        # A high crest factor at the beginning and end must not evade the meter.
        values[12000] = [0.99, -0.99]
        values[-1] = [0.9, -0.9]
    with wave.open(str(path), "wb") as output:
        output.setparams((2, 2, 48000, samples, "NONE", "not compressed"))
        output.writeframes(np.rint(values * 32768).astype("<i2").tobytes())
    return path


def pcm(path):
    with wave.open(str(path)) as source:
        return source.getparams(), np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").reshape(
            -1, 2
        ).astype("int32")


@pytest.mark.parametrize("amplitude", [0.04, 0.6])
def test_quiet_and_loud_sources_reach_consistent_measured_level_without_changing_pitch_or_timing(
    tmp_path, amplitude
):
    source = recording(tmp_path / "source.wav", amplitude)
    original = source.read_bytes()
    output = tmp_path / "master.wav"
    report = master_wave(source, output)
    assert source.read_bytes() == original
    assert report["profile"] == PROFILE and report["target_reached"]
    assert report["after"]["integrated_lufs"] == pytest.approx(-16, abs=0.25)
    assert report["after"]["true_peak_upper_dbfs"] <= -1.5
    shape, values = pcm(output)
    assert shape[:4] == (2, 2, 48000, 240037)
    assert np.array_equal(values[:, 0], values[:, 1])
    # An independent signal property: finishing must not pitch-shift narration
    # or leave the last passage silent after latency compensation.
    region = values[48000:192000, 0]
    frequency = np.argmax(np.abs(np.fft.rfft(region))) * 48000 / len(region)
    assert frequency == pytest.approx(440, abs=1)
    assert np.max(np.abs(values[-512:])) > 1000


def test_high_crest_peaks_are_limited_and_the_last_spoken_samples_remain(tmp_path):
    source = recording(tmp_path / "source.wav", amplitude=0.02, peak=True)
    before = measure(source)
    assert before["sample_peak"] > 0.98
    output = tmp_path / "master.wav"
    report = master_wave(source, output)
    assert report["after"]["true_peak_upper_dbfs"] <= -1.5
    assert report["target_reached"] and report["gain_db"] > 0
    assert pcm(output)[0].nframes == pcm(source)[0].nframes
    assert np.max(np.abs(pcm(output)[1][-32:])) > 1000


@pytest.mark.parametrize("samples", [31, 48001, 240037])
def test_digital_silence_remains_zero_and_is_not_reported_as_target_loudness(tmp_path, samples):
    source = recording(tmp_path / "silence.wav", amplitude=0, samples=samples)
    output = tmp_path / "master.wav"
    report = master_wave(source, output)
    assert report["gain_db"] == 0 and not report["target_reached"]
    assert report["after"]["integrated_lufs"] is None
    assert report["after"]["true_peak_dbfs"] is None
    assert np.count_nonzero(pcm(output)[1]) == 0
    assert pcm(output)[0].nframes == samples


def test_very_quiet_source_has_bounded_gain_and_truthful_attained_loudness(tmp_path):
    source = recording(tmp_path / "quiet.wav", amplitude=0.001)
    report = master_wave(source, tmp_path / "master.wav")
    assert report["gain_db"] == MAX_GAIN_DB
    assert not report["target_reached"] and report["after"]["integrated_lufs"] < -35


def test_known_ebu_stereo_tone_fixture_and_early_true_peak_are_metered(tmp_path):
    # Full-file FFmpeg ebur128 reference for a stereo 440-Hz sine at -40dBFS
    # amplitude is approximately -40.69LUFS, not its unweighted RMS level.
    source = recording(tmp_path / "tone.wav", amplitude=0.01, samples=240000)
    assert measure(source)["integrated_lufs"] == pytest.approx(-40.69, abs=0.05)
    shaped = recording(tmp_path / "peaks.wav", amplitude=0.01, peak=True)
    assert measure(shaped)["true_peak_dbfs"] > -0.2


def test_cancellation_is_checked_during_processing_and_existing_files_are_never_overwritten(tmp_path):
    source = recording(tmp_path / "source.wav")
    output = tmp_path / "master.wav"
    output.write_bytes(b"existing work")
    with pytest.raises(ValueError, match="new private output"):
        master_wave(source, output)
    assert output.read_bytes() == b"existing work"
    linked = tmp_path / "symlink.wav"
    linked.symlink_to(source)
    with pytest.raises(ValueError, match="canonical"):
        master_wave(linked, tmp_path / "new.wav")
    calls = []

    def stop():
        calls.append(True)
        if len(calls) > 5:
            raise InterruptedError("Synthetic Stop")

    with pytest.raises(InterruptedError, match="Synthetic Stop"):
        master_wave(source, tmp_path / "canceled.wav", stop)
    assert source.exists()


def test_truncated_and_oversized_pcm_never_publish_a_master(tmp_path):
    source = recording(tmp_path / "truncated.wav")
    source.write_bytes(source.read_bytes()[:-7])
    with pytest.raises(ValueError, match="truncated"):
        master_wave(source, tmp_path / "master.wav")
    assert not (tmp_path / "master.wav").exists()
    from app.studio_mastering import read_pcm

    huge = tmp_path / "oversized.wav"
    with wave.open(str(huge), "wb") as output:
        output.setparams((2, 2, 48000, 1, "NONE", "not compressed"))
        output.writeframes(b"\0" * 4)
    raw = bytearray(huge.read_bytes())
    raw[40:44] = (600 * 48000 * 4 + 4).to_bytes(4, "little")
    huge.write_bytes(raw)
    with pytest.raises(ValueError, match="within ten minutes"):
        list(read_pcm(huge, lambda: None))
