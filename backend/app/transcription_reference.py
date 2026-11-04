"""Verify and adopt the fixed canonical WAV produced by an owned ASR Run."""

import io
import re
import wave

from app.audio import wav_metadata
from app.python_execution import read_owned_file


def descriptor(run, report):
    value = report.get("normalized_audio")
    if not isinstance(value, dict) or set(value) != {"relative_path", "sha256", "size_bytes"}:
        raise ValueError("Normalized voice reference is missing or invalid")
    if (
        value["relative_path"] != f"runtime/transcription/{run.id}/reference.wav"
        or type(value["size_bytes"]) is not int
        or value["size_bytes"] != 44 + 2 * round(report["duration_seconds"] * 16000)
        or not isinstance(value["sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
    ):
        raise ValueError("Normalized voice reference differs from the transcription")
    return value


def verified_bytes(run, report):
    value = descriptor(run, report)
    data = read_owned_file(
        value["relative_path"], value["size_bytes"], value["sha256"], limit=20 * 1024**2, binary=True
    )
    metadata = wav_metadata(data, max_seconds=300)
    with wave.open(io.BytesIO(data), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16000
            or source.getnframes() != round(report["duration_seconds"] * 16000)
        ):
            raise ValueError("Invalid normalized voice reference WAV")
    return data, metadata
