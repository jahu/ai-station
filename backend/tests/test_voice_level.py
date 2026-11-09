import io
import wave
from uuid import uuid4

import av
import numpy as np
import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run
from app.voice_level_dsp import PROFILE, digest, level_wave, mux_voice
from fastapi.testclient import TestClient


def speech_bytes(channels=1, *, silence=False):
    rate = 16000
    t = np.arange(rate * 3) / rate
    tone = np.sin(t * 2 * np.pi * 170) + 0.3 * np.sin(t * 2 * np.pi * 340)
    values = np.concatenate([tone * gain for gain in [0.03, 0.25, 0.04, 0.3, 0.06]])
    if silence:
        values *= 0
    samples = np.repeat(values[:, None], channels, axis=1)
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes((samples * 32767).astype("<i2").tobytes())
    return output.getvalue()


@pytest.mark.parametrize("channels,silence", [(1, False), (2, False), (1, True)])
def test_leveling_has_fixed_timing_finite_gain_and_reduces_level_changes(tmp_path, channels, silence):
    source, output = tmp_path / "original.wav", tmp_path / "balanced.wav"
    source.write_bytes(speech_bytes(channels, silence=silence))
    sha = digest(source)
    report = level_wave(source, output)
    assert digest(source) == sha
    assert report["profile"] == PROFILE
    with wave.open(str(source)) as a, wave.open(str(output)) as b:
        assert a.getnframes() == b.getnframes() == report["samples"]
        assert a.getframerate() == b.getframerate()
        assert b.getnchannels() == channels
        samples = np.frombuffer(b.readframes(b.getnframes()), dtype="<i2")
    assert np.max(np.abs(samples.astype(float))) <= 32767 * 0.9
    if silence:
        assert not np.any(samples)
    else:
        assert report["after"]["active_range_db"] < report["before"]["active_range_db"] - 3
        assert report["after"]["peak_dbfs"] <= 0
    with pytest.raises(ValueError, match="new speech output"):
        level_wave(source, output)


def upload(client):
    r = client.post("/api/audio/uploads", files={"file": ("voice.wav", speech_bytes(), "audio/wav")})
    assert r.status_code == 201, r.text
    return r.json()


def enqueue(client, source, key=None):
    return client.post(
        f"/api/artifacts/{source['id']}/voice-level", json={"client_request_id": key or str(uuid4())}
    )


def test_library_repair_is_idempotent_and_preserves_original_and_lineage():
    with TestClient(app) as client:
        original = upload(client)
        key = str(uuid4())
        r = enqueue(client, original, key)
        assert r.status_code == 202, r.text
        assert enqueue(client, original, key).json()["id"] == r.json()["id"]
        with session_factory()() as session:
            tick(session, "voice-test")
        run = client.get(f"/api/runs/{r.json()['id']}").json()
        assert run["status"] == "succeeded", run
        result = client.get(f"/api/artifacts/{run['metadata']['result_artifact_id']}").json()
        assert result["parent_artifact_ids"] == [original["id"]]
        assert result["metadata"]["audio_leveling"]["profile"] == PROFILE
        assert result["sha256"] != original["sha256"]
        assert client.get(f"/api/artifacts/{original['id']}").json()["sha256"] == original["sha256"]
        assert enqueue(client, result).status_code == 409
        assert client.get(f"/api/artifacts/{result['id']}/file").status_code == 200
        from types import SimpleNamespace

        from app.voice_level import finish_generated

        with session_factory()() as session:
            executor = SimpleNamespace(name="sonic_whole", artifact_type="video")
            run = SimpleNamespace(
                parameters={
                    "level_volume": True,
                    "audio_level_profile": PROFILE,
                    "parent_artifact_ids": [result["id"]],
                }
            )
            output, metadata = finish_generated(executor, session, run, (None, None), "unchanged.mp4")
            assert output == "unchanged.mp4"
            assert metadata["audio_leveling"]["inherited_from_artifact_id"] == result["id"]
            for parameters in ({}, {"level_volume": False}):
                run.parameters = parameters
                assert finish_generated(executor, session, run, (None, None), "unchanged.mp4") == (
                    "unchanged.mp4",
                    {},
                )


@pytest.mark.parametrize("mutation", ["cancel", "claim", "trash"])
def test_processing_does_not_publish_after_cancel_lost_claim_or_source_removal(monkeypatch, mutation):
    import app.voice_level as module
    from app.db import utcnow
    from app.runs import request_cancel

    with TestClient(app) as client:
        source = upload(client)
        response = enqueue(client, source)
        identity = response.json()["id"]
        original = module.level_wave

        def change(*args):
            report = original(*args)
            with session_factory()() as other:
                run = other.get(Run, identity)
                if mutation == "cancel":
                    request_cancel(other, run)
                elif mutation == "claim":
                    run.worker_id = "replacement-worker"
                else:
                    other.get(Artifact, source["id"]).trashed_at = utcnow()
                other.commit()
            return report

        monkeypatch.setattr(module, "level_wave", change)
        with session_factory()() as session:
            tick(session, "voice-test")
        run = client.get(f"/api/runs/{identity}").json()
        assert run["status"] == {"cancel": "canceled", "claim": "running", "trash": "failed"}[mutation]
        assert client.get("/api/artifacts", params={"run_id": identity}).json() == []


@pytest.mark.parametrize("change", ["symlink", "bytes"])
def test_canonical_symlink_and_changed_bytes_are_rejected(change):
    with TestClient(app) as client:
        original = upload(client)
        response = enqueue(client, original)
        root = get_settings().data_dir
        source = root / original["relative_path"]
        replacement = root / "replacement.wav"
        if change == "symlink":
            source.rename(replacement)
            source.symlink_to(replacement)
        else:
            source.write_bytes(b"changed")
        with session_factory()() as session:
            tick(session, "voice-test")
        run = client.get(f"/api/runs/{response.json()['id']}").json()
        assert run["status"] == "failed"
        assert client.get("/api/artifacts", params={"run_id": run["id"]}).json() == []


def test_video_repair_copies_all_encoded_picture_packets(tmp_path):
    silent = tmp_path / "silent.mp4"
    with av.open(str(silent), "w") as dst:
        stream = dst.add_stream("libx264", rate=25)
        stream.width = stream.height = 64
        stream.pix_fmt = "yuv420p"
        for i in range(50):
            frame = av.VideoFrame.from_ndarray(np.full((64, 64, 3), i * 4, dtype=np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                dst.mux(packet)
        for packet in stream.encode():
            dst.mux(packet)
    source = tmp_path / "voice.wav"
    source.write_bytes(speech_bytes())
    report = level_wave(source, tmp_path / "balanced.wav")
    out = tmp_path / "balanced.mp4"
    mux_voice(silent, tmp_path / "balanced.wav", out, report)
    assert report["video_reencoded"] is False
    with av.open(str(silent)) as a, av.open(str(out)) as b:
        before = [(p.pts, p.dts, bytes(p)) for p in a.demux(video=0) if p.dts is not None]
        after = [(p.pts, p.dts, bytes(p)) for p in b.demux(video=0) if p.dts is not None]
        assert before == after
        assert len(b.streams.audio) == 1


def test_missing_or_invalid_media_is_not_enqueued():
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/artifacts/{uuid4()}/voice-level", json={"client_request_id": str(uuid4())}
            ).status_code
            == 422
        )
        original = upload(client)
        assert (
            client.post(
                f"/api/artifacts/{original['id']}/voice-level",
                json={"client_request_id": str(uuid4()), "filters": "unsafe"},
            ).status_code
            == 422
        )
