"""Separate optional CPU runtime. All model and audio inputs stay offline."""

import hashlib
import io
import json
import os
import signal
import sys
import wave
from pathlib import Path
from uuid import UUID

from ai_station_runner.security import resolve_child
from ai_station_runner.transcription_protocol import audio_bytes, profile, validate_report, wav_info


def execute(run_id, data_root, model_root):
    import av
    import numpy as np
    from faster_whisper import WhisperModel

    signal.alarm(600)
    root = resolve_child(Path(data_root), f"runtime/transcription/{UUID(run_id)}")
    request_path = resolve_child(root, "request.json")
    if request_path.stat().st_size > 8192:
        raise ValueError("Request exceeds its limit")
    body = json.loads(request_path.read_text())
    if body["run_id"] != run_id or set(body["permissions"]) != {"filesystem_read", "workspace_write"}:
        raise ValueError("Request ownership changed")
    if profile(model_root) != body["profile_sha256"]:
        raise ValueError("Model changed since submission")
    with resolve_child(Path(model_root), "ai-station-model.json").open("rb") as handle:
        model_bytes = handle.read(16385)
    if len(model_bytes) > 16384 or hashlib.sha256(model_bytes).hexdigest() != body["profile_sha256"]:
        raise ValueError("Model manifest changed before loading")
    model_manifest = json.loads(model_bytes)
    data = audio_bytes(data_root, body["source"])
    metadata = wav_info(data)
    with wave.open(io.BytesIO(data), "rb") as source:
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32)
    samples = samples.reshape(-1, metadata["channels"]).mean(axis=1) / 32768.0
    if metadata["sample_rate"] != 16000:
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = metadata["sample_rate"]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
        frames = resampler.resample(frame) + resampler.resample(None)
        samples = np.concatenate([item.to_ndarray().reshape(-1) for item in frames])
    model = WhisperModel(
        str(model_root),
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
        local_files_only=True,
    )
    stream, info = model.transcribe(
        samples,
        language=None if body["language"] == "auto" else body["language"],
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    segments = []
    previous = 0.0
    for segment in stream:
        start = max(previous, min(metadata["duration_seconds"], segment.start))
        end = max(start, min(metadata["duration_seconds"], segment.end))
        segments.append({"start": start, "end": end, "text": segment.text.strip()})
        previous = end
        if len(segments) > 2000 or sum(len(s["text"]) for s in segments) > 100000:
            raise ValueError("Transcript exceeds its limit")
    value = {
        "model": str(model_manifest.get("model", "Whisper offline"))[:200],
        "model_revision": str(model_manifest.get("revision", ""))[:200],
        "run_id": run_id,
        "source_sha256": body["source"]["sha256"],
        "profile_sha256": body["profile_sha256"],
        "device": "cpu",
        "language": info.language,
        "duration_seconds": metadata["duration_seconds"],
        "segments": segments,
        "text": "\n".join(s["text"] for s in segments),
    }
    validate_report(
        value, run_id=run_id, source_hash=body["source"]["sha256"], profile_hash=body["profile_sha256"]
    )
    output = resolve_child(root, "report.json")
    with output.open("x") as handle:
        os.chmod(output, 0o600)
        json.dump(value, handle, ensure_ascii=False)
    signal.alarm(0)
    print(f"Transcribed {metadata['duration_seconds']:.1f}s locally on CPU.", flush=True)


if __name__ == "__main__":
    try:
        execute(*sys.argv[1:])
    except Exception:
        print(
            "Local transcription failed; inspect the configured runtime, model and WAV recording.",
            file=sys.stderr,
        )
        sys.exit(1)
