"""Canonical voice references from the exact PCM used by offline transcription."""

import hashlib
import io
import os
import re
import stat
import wave
from pathlib import Path

from ai_station_runner.security import resolve_child
from ai_station_runner.transcription_protocol import wav_info


def reference_path(run_id):
    from uuid import UUID

    return f"runtime/transcription/{UUID(run_id)}/reference.wav"


def validate_descriptor(value, run_id, duration):
    if (
        not isinstance(value, dict)
        or set(value) != {"relative_path", "size_bytes", "sha256"}
        or value["relative_path"] != reference_path(run_id)
        or type(value["size_bytes"]) is not int
        or value["size_bytes"] != 44 + 2 * round(duration * 16000)
        or not isinstance(value["sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
    ):
        raise ValueError("Normalized reference differs from the transcription")
    return value


def save(root, run_id, samples):
    import numpy as np

    if samples.ndim != 1 or not 1600 <= len(samples) <= 300 * 16000 or not np.isfinite(samples).all():
        raise ValueError("Invalid normalized reference samples")
    content = io.BytesIO()
    with wave.open(content, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(np.rint(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    data = content.getvalue()
    relative = reference_path(run_id)
    path = resolve_child(Path(root), relative)
    if path != Path(root) / relative:
        raise ValueError("Normalized reference must be a direct owned file")
    with path.open("xb") as output:
        path.chmod(0o600)
        output.write(data)
    return {"relative_path": relative, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def verify(root, value, run_id, duration):
    validate_descriptor(value, run_id, duration)
    path = resolve_child(Path(root), value["relative_path"])
    if path != Path(root) / value["relative_path"]:
        raise ValueError("Normalized reference must be a direct owned file")
    handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(handle, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != value["size_bytes"]:
            raise ValueError("Normalized reference must be the recorded regular file")
        data = source.read(value["size_bytes"] + 1)
        after = os.fstat(source.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Normalized reference changed while reading")
    if hashlib.sha256(data).hexdigest() != value["sha256"]:
        raise ValueError("Normalized reference changed")
    wav_info(data)
    with wave.open(io.BytesIO(data), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16000
            or source.getnframes() != round(duration * 16000)
            or len(source.readframes(source.getnframes())) != value["size_bytes"] - 44
        ):
            raise ValueError("Invalid normalized reference WAV")
    return value
