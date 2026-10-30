"""Real small CPU codecs; no models, GPU, external services or host mutations."""

import hashlib
import json
import time
import wave
from uuid import uuid4

import av
import numpy as np
import pytest
from ai_station_runner import timeline_job as job
from ai_station_runner.timeline_contract import TimelineRequest


def fixture(tmp_path):
    artifact = tmp_path / "artifacts"
    artifact.mkdir()
    values = []
    for fps, frames, filename in [(24, 48, "first.mp4"), (25, 25, "second.mp4")]:
        path = artifact / filename
        with av.open(str(path), "w") as output:
            stream = output.add_stream("libx264", rate=fps)
            stream.width = stream.height = 128
            stream.pix_fmt = "yuv420p"
            for i in range(frames):
                color = [0, 200, 0] if fps == 25 else [200, 0, 0] if i < 24 else [0, 0, 200]
                image = np.zeros((128, 128, 3), dtype=np.uint8)
                image[:] = color
                frame = av.VideoFrame.from_ndarray(image, format="rgb24")
                frame.pts = i
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)
        values.append(
            {
                "artifact_id": str(uuid4()),
                "kind": "video",
                "relative_path": "artifacts/" + filename,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "frames": frames,
                "fps": fps,
                "width": 128,
                "height": 128,
            }
        )
    path = artifact / "tone.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(
            (np.sin(np.arange(24000) * 2 * np.pi * 500 / 24000) * 16000).astype("<i2").tobytes()
        )
    values.append(
        {
            "artifact_id": str(uuid4()),
            "kind": "audio",
            "relative_path": "artifacts/tone.wav",
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "samples": 24000,
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 2,
        }
    )
    return TimelineRequest.model_validate(
        {
            "run_id": str(uuid4()),
            "deadline_at": time.time() + 60,
            "observation": "a" * 64,
            "permissions": ["filesystem_read", "workspace_write"],
            "sources": values,
            "manifest": {
                "fps": 24,
                "width": 128,
                "height": 128,
                "clips": [
                    {
                        "artifact_id": values[0]["artifact_id"],
                        "in_frame": 24,
                        "out_frame": 48,
                        "start_frame": 0,
                        "muted": True,
                    },
                    {
                        "artifact_id": values[1]["artifact_id"],
                        "in_frame": 0,
                        "out_frame": 25,
                        "start_frame": 48,
                        "muted": True,
                    },
                ],
                "tracks": [
                    {
                        "artifact_id": values[2]["artifact_id"],
                        "duration_frames": 24,
                        "start_frame": 24,
                        "fade_in_frames": 6,
                        "fade_out_frames": 6,
                    }
                ],
            },
        }
    )


def test_trim_move_gaps_rate_conversion_and_audio_mix_produce_the_exact_film(tmp_path, monkeypatch):
    request = fixture(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "memory.peak").write_text("4096")
    monkeypatch.setattr(job, "current_group", lambda: tmp_path)
    output = tmp_path / "artifacts/export.mp4"
    report = job.render(request, tmp_path, work, output)
    assert report["verified"] and report["frames"] == 72 and report["timeline_audio_samples"] == 144000
    assert report["peak_protection_gain"] == 1
    assert output.stat().st_nlink == 1
    colors = []
    with av.open(str(output)) as media:
        for index, frame in enumerate(media.decode(video=0)):
            if index in [0, 24, 48]:
                colors.append(frame.to_ndarray(format="rgb24").mean(axis=(0, 1)))
    assert colors[0][2] > 180 and max(colors[0][:2]) < 10
    assert max(colors[1]) < 10
    assert colors[2][1] > 180 and colors[2][0] < 10
    assert json.loads(output.with_suffix(".json").read_text())["verified"] is True
    sources = {str(s.artifact_id): s for s in request.sources}
    paths = {k: tmp_path / s.relative_path for k, s in sources.items()}
    mixed, _ = job.mix_audio(av, np, request, paths, sources, 72)
    assert np.max(np.abs(mixed[:48000])) == 0 and np.max(np.abs(mixed[96000:])) == 0
    assert np.max(np.abs(mixed[50000:94000])) > 0.1
    assert mixed[48000].tolist() == [0, 0] and mixed[95999].tolist() == [0, 0]


def test_mute_and_peak_protection_keep_mix_finite_and_report_the_adjustment(tmp_path):
    request = fixture(tmp_path)
    sources = {str(s.artifact_id): s for s in request.sources}
    paths = {k: tmp_path / s.relative_path for k, s in sources.items()}
    track = request.manifest.tracks[0]
    track.gain = 4.0
    mixed, report = job.mix_audio(av, np, request, paths, sources, 72)
    assert report["peak_protection_gain"] < 1 and np.max(np.abs(mixed)) <= 0.98001
    track.muted = True
    muted, report = job.mix_audio(av, np, request, paths, sources, 72)
    assert np.max(np.abs(muted)) == 0 and report["peak_protection_gain"] == 1


def test_changed_source_after_encode_never_publishes_a_film(tmp_path, monkeypatch):
    request = fixture(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    verify = job.verify

    def mutate(*args):
        report = verify(*args)
        (tmp_path / request.sources[0].relative_path).write_bytes(b"changed media")
        return report

    monkeypatch.setattr(job, "verify", mutate)
    with pytest.raises(ValueError, match="observation|content"):
        job.render(request, tmp_path, work, tmp_path / "artifacts/export.mp4")
    assert not (tmp_path / "artifacts/export.mp4").exists()


def test_original_video_audio_is_trimmed_faded_and_muted_independently(tmp_path):
    request = fixture(tmp_path)
    source = request.sources[0]
    path = tmp_path / source.relative_path
    with av.open(str(path), "w") as media:
        video = media.add_stream("libx264", rate=24)
        video.width = video.height = 128
        video.pix_fmt = "yuv420p"
        audio = media.add_stream("aac", rate=48000)
        audio.layout = "stereo"
        for index in range(48):
            frame = av.VideoFrame.from_ndarray(np.zeros((128, 128, 3), dtype=np.uint8), format="rgb24")
            frame.pts = index
            for packet in video.encode(frame):
                media.mux(packet)
            positions = np.arange(index * 2000, (index + 1) * 2000)
            samples = (np.sin(positions * 2 * np.pi * 500 / 48000) * 0.5).astype(np.float32)
            sound = av.AudioFrame.from_ndarray(np.stack([samples, samples]), format="fltp", layout="stereo")
            sound.sample_rate, sound.pts = 48000, index * 2000
            for packet in audio.encode(sound):
                media.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode():
                media.mux(packet)
    clip = request.manifest.clips[0]
    clip.muted, clip.gain = False, 0.2
    clip.fade_in_frames = clip.fade_out_frames = 6
    request.manifest.clips, request.manifest.tracks = [clip], []
    sources = {str(source.artifact_id): source}
    paths = {str(source.artifact_id): path}
    mixed, _ = job.mix_audio(av, np, request, paths, sources, 24)
    assert mixed.shape == (48000, 2)
    assert 0.07 < np.max(np.abs(mixed)) < 0.14
    assert mixed[0].tolist() == [0, 0] and mixed[-1].tolist() == [0, 0]
    clip.muted = True
    muted, _ = job.mix_audio(av, np, request, paths, sources, 24)
    assert np.max(np.abs(muted)) == 0
