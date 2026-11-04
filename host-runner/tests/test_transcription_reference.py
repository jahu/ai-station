import hashlib
import io
import wave
from uuid import uuid4

import numpy as np
import pytest
from ai_station_runner.transcription_reference import reference_path, save, validate_descriptor, verify
from test_runner_transcription import setup as setup


def setup_reference(tmp_path):
    run_id = str(uuid4())
    (tmp_path / reference_path(run_id)).parent.mkdir(parents=True)
    samples = np.linspace(-1, 1, 3200, dtype=np.float32)
    descriptor = save(tmp_path, run_id, samples)
    return run_id, descriptor


def test_canonical_pcm_is_complete_private_and_bound_to_exact_decoded_samples(tmp_path):
    run_id, descriptor = setup_reference(tmp_path)
    assert verify(tmp_path, descriptor, run_id, 0.2) == descriptor
    path = tmp_path / reference_path(run_id)
    assert path.stat().st_mode & 0o777 == 0o600
    with wave.open(str(path), "rb") as source:
        pcm = np.frombuffer(source.readframes(3200), dtype="<i2")
        assert source.getparams()[:4] == (1, 2, 16000, 3200)
        assert (pcm[[0, -1]] == [-32767, 32767]).all()
    with pytest.raises(FileExistsError):
        save(tmp_path, run_id, np.zeros(3200))


@pytest.mark.parametrize("samples", [np.zeros(1599), np.zeros((1600, 2)), np.full(1600, np.nan)])
def test_invalid_samples_publish_nothing(tmp_path, samples):
    run_id = str(uuid4())
    with pytest.raises(ValueError, match="samples"):
        save(tmp_path, run_id, samples)
    assert not (tmp_path / reference_path(run_id)).exists()


def test_requested_normalization_requires_confirmed_complete_native_output(setup):
    from ai_station_runner import transcription as tr
    from ai_station_runner.processes import ProcessManager
    from test_runner_transcription import wait

    root, _, body = setup
    body = body.model_copy(update={"normalize_reference": True})
    manager = ProcessManager(root)
    try:
        tr.start(manager, body)
        assert wait(manager, str(body.run_id))["exit_code"] == 0
        # The legacy synthetic child writes text but no canonical WAV.
        with pytest.raises(ValueError, match="normalization differs"):
            tr.report(manager, str(body.run_id))
    finally:
        manager.shutdown()


@pytest.mark.parametrize(
    "field,value", [("relative_path", "artifacts/other.wav"), ("size_bytes", True), ("sha256", "wrong")]
)
def test_descriptor_cannot_choose_other_files_or_change_sample_count(tmp_path, field, value):
    run_id, descriptor = setup_reference(tmp_path)
    with pytest.raises(ValueError):
        validate_descriptor({**descriptor, field: value}, run_id, 0.2)
    with pytest.raises(ValueError):
        validate_descriptor(descriptor, run_id, 0.3)


@pytest.mark.parametrize("change", ["bytes", "format", "symlink", "header"])
def test_changed_redirected_or_noncanonical_wav_is_rejected(tmp_path, change):
    run_id, descriptor = setup_reference(tmp_path)
    path = tmp_path / reference_path(run_id)
    if change == "bytes":
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
    elif change == "format":
        data = io.BytesIO()
        with wave.open(data, "wb") as source:
            source.setnchannels(1)
            source.setsampwidth(2)
            source.setframerate(8000)
            source.writeframes(b"\0\0" * 3200)
        path.write_bytes(data.getvalue())
        descriptor["sha256"] = hashlib.sha256(data.getvalue()).hexdigest()
    elif change == "header":
        data = b"!" + path.read_bytes()[1:]
        path.write_bytes(data)
        descriptor["sha256"] = hashlib.sha256(data).hexdigest()
    else:
        outside = tmp_path.parent / f"outside-{run_id}.wav"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    with pytest.raises(ValueError):
        verify(tmp_path, descriptor, run_id, 0.2)


@pytest.mark.parametrize("normalize", [False, True])
def test_entry_writes_canonical_wav_only_after_complete_transcription(setup, monkeypatch, normalize):
    import json
    import sys
    from types import SimpleNamespace

    from ai_station_runner import transcription as tr
    from ai_station_runner import transcription_decode, transcription_entry

    root, model, body = setup
    rid = str(body.run_id)
    directory = tr.directory(rid)
    directory.mkdir(parents=True)
    request = body.model_copy(update={"normalize_reference": normalize})
    (directory / "request.json").write_text(request.model_dump_json())
    samples = np.linspace(-0.5, 0.5, 16000, dtype=np.float32)
    monkeypatch.setattr(
        transcription_decode, "decode", lambda data: (samples, {"duration_seconds": 1, "input_format": "wav"})
    )

    class Model:
        def __init__(self, path, **kwargs):
            assert kwargs["device"] == "cpu" and kwargs["local_files_only"] is True

        def transcribe(self, pcm, **kwargs):
            assert pcm is samples
            return iter([SimpleNamespace(start=0, end=1, text="Reference words")]), SimpleNamespace(
                language="en"
            )

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    transcription_entry.execute(rid, root, model)
    report = json.loads((directory / "report.json").read_text())
    assert report["text"] == "Reference words"
    assert ("normalized_audio" in report) is normalize
    assert (root / reference_path(rid)).exists() is normalize
    if normalize:
        verify(root, report["normalized_audio"], rid, 1)


def test_failed_transcript_does_not_write_reference_or_report(setup, monkeypatch):
    import sys
    from types import SimpleNamespace

    from ai_station_runner import transcription as tr
    from ai_station_runner import transcription_decode, transcription_entry

    root, model, body = setup
    rid = str(body.run_id)
    directory = tr.directory(rid)
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(
        body.model_copy(update={"normalize_reference": True}).model_dump_json()
    )
    monkeypatch.setattr(
        transcription_decode,
        "decode",
        lambda data: (np.zeros(16000), {"duration_seconds": 1, "input_format": "wav"}),
    )

    class Model:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            def failed():
                yield SimpleNamespace(start=0, end=0.5, text="Partial")
                raise ValueError("inference failed")

            return failed(), SimpleNamespace(language="en")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    # The real child exits on failure; restore its alarm in this in-process fake.
    import signal

    try:
        with pytest.raises(ValueError, match="inference failed"):
            transcription_entry.execute(rid, root, model)
    finally:
        signal.alarm(0)
    assert not (directory / "report.json").exists()
    assert not (root / reference_path(rid)).exists()
