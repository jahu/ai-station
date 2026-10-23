"""Pinned offline music inputs and bounded PCM output verification.

This module does not activate a native endpoint or import an inference runtime.
"""

import hashlib
import json
import wave
from pathlib import Path

from ai_station_runner.security import resolve_child

MODEL_REVISION = "19671f406d603126926c1b7e2adc169acbcade22"
CODE_REVISION = "ca1e85fe9430179831e6bc6be790c332190a3866"
MANIFEST_SHA256 = "912b4a5cd50f729d8874dcbd44776d87643f04d199b748ba3706b7181a69c658"
SOURCE_SHA256 = "f5ad978f98ccdc04dc2bd6bb0271e51494f11a0ffd8932113163b6a2d3c810ef"
MAX_SECONDS = 600
MAX_BYTES = 240 * 1024 * 1024


def no_symlink(path):
    path = Path(path).expanduser().absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Music paths must not contain symlinks")
    return path.resolve(strict=True)


def model_manifest(model_root, *, verify_weights=False):
    root = no_symlink(model_root)
    receipt = no_symlink(root / "ai-station-model.json")
    if receipt.stat().st_size > 16384:
        raise ValueError("Music model receipt exceeds its limit")
    manifest = json.loads(receipt.read_text())
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Music checkpoint is not the approved pinned preset")
    for item in manifest["files"]:
        path = no_symlink(root / item["path"])
        if path != resolve_child(root, item["path"]):
            raise ValueError("Music model file escaped its root")
        if not path.is_file() or path.stat().st_size != item["size"]:
            raise ValueError(f"Music file is missing or changed: {item['path']}")
        # Hash model code on every inspection, and all weights in the worker's
        # owned process before inference. HTTP capability checks never read GBs.
        if verify_weights or path.suffix == ".py":
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError(f"Music file failed SHA-256: {item['path']}")
    return manifest


def verify_source(source_root):
    root = no_symlink(Path(source_root) / "acestep")
    digest = hashlib.sha256()
    paths = sorted(root.rglob("*.py"))
    if not paths:
        raise ValueError("Music runtime sources are missing")
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        no_symlink(path)
        name = path.relative_to(root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    if digest.hexdigest() != SOURCE_SHA256:
        raise ValueError("Music runtime sources differ from the approved pinned revision")
    return root


def checkpoint_view(model_root, source_root, destination):
    """Create an owned per-Run view; upstream code sync never touches weights."""
    import shutil

    manifest = model_manifest(model_root, verify_weights=True)
    source = verify_source(source_root)
    destination = Path(destination)
    destination.mkdir(mode=0o700, exist_ok=False)
    for item in manifest["files"]:
        target = destination / item["path"]
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if target.suffix == ".py":
            # The pinned upstream package's matching model implementation is
            # authoritative. Its initializer would otherwise rewrite model code.
            shutil.copyfile(source / "models/turbo" / target.name, target)
        else:
            target.symlink_to(no_symlink(Path(model_root) / item["path"]))
    return destination


def wav_metadata(path, *, requested_seconds=None):
    path = no_symlink(path)
    if not path.is_file() or not 44 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("Music output is missing or exceeds its WAV limit")
    try:
        with wave.open(str(path), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if (
                channels not in {1, 2}
                or rate != 48000
                or width != 2
                or not 10 <= frames / rate <= MAX_SECONDS + 1
            ):
                raise ValueError("Music output must be 48 kHz mono/stereo 16-bit PCM WAV, 10–600 s")
            duration = frames / rate
            if requested_seconds is not None and abs(duration - requested_seconds) > 1:
                raise ValueError("Music output duration does not match the requested duration")
            remaining, audible = frames, False
            while remaining:
                count = min(remaining, 48000)
                chunk = audio.readframes(count)
                if len(chunk) != count * channels * width:
                    raise ValueError("Music output contains truncated PCM frames")
                audible = audible or bool(chunk.strip(b"\0"))
                remaining -= count
            if not audible:
                raise ValueError("Music runtime returned entirely silent audio")
            return {"duration_seconds": duration, "sample_rate": rate, "channels": channels}
    except (wave.Error, EOFError) as exc:
        raise ValueError("Music runtime did not return a valid PCM WAV") from exc
