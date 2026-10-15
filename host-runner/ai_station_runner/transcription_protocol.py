"""Offline transcription bounds shared with the separately installed runtime."""

import hashlib
import io
import json
import math
import wave
from pathlib import Path

from ai_station_runner.security import resolve_child

MAX_BYTES = 20 * 1024 * 1024
MAX_SECONDS = 300
MODEL_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")


def profile(directory):
    root = Path(directory).expanduser().resolve(strict=True)
    manifest = resolve_child(root, "ai-station-model.json")
    if manifest.stat().st_size > 16384:
        raise ValueError("Transcription model manifest exceeds its limit")
    manifest_bytes = manifest.read_bytes()
    if len(manifest_bytes) > 16384:
        raise ValueError("Transcription model manifest exceeds its limit")
    value = json.loads(manifest_bytes)
    if not isinstance(value, dict) or not isinstance(value.get("files"), dict):
        raise ValueError("Invalid transcription model manifest")
    files = list(MODEL_FILES)
    if resolve_child(root, "preprocessor_config.json").exists():
        files.append("preprocessor_config.json")
    for name in files:
        path = resolve_child(root, name)
        entry = value["files"].get(name)
        if (
            not isinstance(entry, dict)
            or type(entry.get("size")) is not int
            or entry["size"] < 1
            or not isinstance(entry.get("sha256"), str)
        ):
            raise ValueError("Invalid transcription model file manifest")
        if path.stat().st_size != entry["size"]:
            raise ValueError("Transcription model size differs from its manifest")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise ValueError("Transcription model differs from its manifest")
    return hashlib.sha256(manifest_bytes).hexdigest()


def audio_bytes(root, source):
    path = resolve_child(Path(root), source["relative_path"])
    if path.stat().st_size != source["size_bytes"] or path.stat().st_size > MAX_BYTES:
        raise ValueError("Recording size changed or exceeds 20 MiB")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if hashlib.sha256(data).hexdigest() != source["sha256"]:
        raise ValueError("Recording changed since submission")
    wav_info(data)
    return data


def wav_info(data):
    if len(data) > MAX_BYTES:
        raise ValueError("Recording exceeds 20 MiB")
    try:
        with wave.open(io.BytesIO(data), "rb") as source:
            rate, frames, channels = source.getframerate(), source.getnframes(), source.getnchannels()
            if (
                source.getsampwidth() != 2
                or channels not in {1, 2}
                or not 8000 <= rate <= 96000
                or not 0.1 <= frames / rate <= MAX_SECONDS
            ):
                raise ValueError("Use 16-bit PCM WAV, mono/stereo, 8000–96000 Hz, up to five minutes")
            if len(source.readframes(frames)) != frames * channels * 2:
                raise ValueError("Recording is truncated")
            return {"duration_seconds": frames / rate, "sample_rate": rate, "channels": channels}
    except (wave.Error, EOFError) as exc:
        raise ValueError("Use a complete 16-bit PCM WAV recording") from exc


def validate_report(value, *, run_id, source_hash, profile_hash):
    if len(json.dumps(value).encode()) > 512000:
        raise ValueError("Transcript exceeds its limit")
    if (
        value.get("run_id") != run_id
        or value.get("source_sha256") != source_hash
        or value.get("profile_sha256") != profile_hash
        or value.get("device") != "cpu"
    ):
        raise ValueError("Transcript ownership or model differs from the request")
    duration = value.get("duration_seconds")
    if (
        type(duration) not in {int, float}
        or not math.isfinite(duration)
        or not 0.1 <= duration <= MAX_SECONDS
    ):
        raise ValueError("Invalid transcript duration")
    text, segments, language = value.get("text"), value.get("segments"), value.get("language")
    if (
        not isinstance(text, str)
        or len(text) > 100000
        or not isinstance(segments, list)
        or len(segments) > 2000
    ):
        raise ValueError("Invalid transcript content")
    if not isinstance(language, str) or not 2 <= len(language) <= 3 or not language.isalpha():
        raise ValueError("Invalid transcript language")
    previous = 0.0
    for item in segments:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or len(item["text"]) > 10000:
            raise ValueError("Invalid transcript segment")
        start, end = item.get("start"), item.get("end")
        if any(type(v) not in {int, float} or not math.isfinite(v) for v in (start, end)):
            raise ValueError("Invalid transcript timing")
        if not previous <= start <= end <= duration:
            raise ValueError("Transcript timing is out of bounds")
        previous = end
    if text != "\n".join(item["text"] for item in segments):
        raise ValueError("Transcript text differs from its segments")
    return value
