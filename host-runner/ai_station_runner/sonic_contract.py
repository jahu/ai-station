"""Fixed whole-recording candidate identity, shared with its offline model Python.

This is a qualification boundary, not an advertised production executor. Keep
the native imports Python 3.10 compatible and free of inference dependencies.
"""

import hashlib
import json
import math
import re
import time
import wave
from pathlib import Path
from uuid import UUID

from ai_station_runner.security import resolve_child
from ai_station_runner.whole_avatar_timing import WholeAvatarTiming, portrait_canvas, whole_portrait_canvas

PROFILE = "sonic_whole_768_v1"
SOURCE_REVISION = "c1bd2d133ecc72f1a5abd990f1de101efcc3cfdb"
MODEL_FILES = (
    "RIFE/flownet.pkl",
    "Sonic/audio2bucket.pth",
    "Sonic/audio2token.pth",
    "Sonic/unet.pth",
    "yoloface_v5m.pt",
    "stable-video-diffusion-img2vid-xt/image_encoder/config.json",
    "stable-video-diffusion-img2vid-xt/image_encoder/model.fp16.safetensors",
    "stable-video-diffusion-img2vid-xt/scheduler/scheduler_config.json",
    "stable-video-diffusion-img2vid-xt/unet/config.json",
    "stable-video-diffusion-img2vid-xt/vae/config.json",
    "stable-video-diffusion-img2vid-xt/vae/diffusion_pytorch_model.fp16.safetensors",
    "whisper-tiny/config.json",
    "whisper-tiny/model.safetensors",
    "whisper-tiny/preprocessor_config.json",
)
IMPLEMENTATION_FILES = (
    "sonic_contract.py",
    "sonic_entry.py",
    "sonic_frames.py",
    "sonic_guidance.py",
    "sonic_inference.py",
    "sonic_jobs.py",
    "sonic_runtime.py",
    "sonic_progress.py",
    "whole_avatar_timing.py",
    "memory_scope.py",
    "security.py",
)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def direct_file(root, relative):
    root = Path(root).resolve()
    if type(relative) is not str or "\\" in relative:
        raise ValueError("Use a canonical relative file without symlinks")
    path = resolve_child(root, relative)
    if path != root / relative or not path.is_file() or path.relative_to(root).as_posix() != relative:
        raise ValueError("Use a canonical relative file without symlinks")
    return path


def installation_observation(runtime, models):
    """Hash the actual imported source, fixed weights and owned adapter code.

    Paths are configuration, never caller-supplied inference controls. Hashing
    is deliberate: a same-size replaced checkpoint must not retain its identity.
    Native entry checks this again before importing any upstream model code.
    """
    runtime, models = Path(runtime).resolve(), Path(models).resolve()
    required = (
        "sonic.py",
        "config/inference/sonic.yaml",
        "src/pipelines/pipeline_sonic.py",
        "src/dataset/test_preprocess.py",
    )
    for relative in required:
        direct_file(runtime, relative)
    if any(path.is_symlink() for path in (runtime / "src").rglob("*")):
        raise ValueError("Sonic source must not import through symlinks")
    source_paths = sorted(
        {"sonic.py", "config/inference/sonic.yaml"}
        | {path.relative_to(runtime).as_posix() for path in (runtime / "src").rglob("*.py")}
    )
    if len(source_paths) > 512:
        raise ValueError("Unexpected Sonic source inventory")
    implementation = Path(__file__).parent
    files = {}
    for kind, root, names in (
        ("source", runtime, source_paths),
        ("models", models, MODEL_FILES),
        ("adapter", implementation, IMPLEMENTATION_FILES),
    ):
        for relative in names:
            path = direct_file(root, relative)
            files[kind + "/" + relative] = {"size_bytes": path.stat().st_size, "sha256": digest(path)}
    identity = {"profile": PROFILE, "upstream_reference_revision": SOURCE_REVISION, "files": files}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def checked_recipe(value):
    if (
        type(value) is not dict
        or set(value) != {"id", "observation"}
        or value["id"] != PROFILE
        or type(value["observation"]) is not str
        or re.fullmatch("[0-9a-f]{64}", value["observation"]) is None
    ):
        raise ValueError("Choose the frozen whole-recording avatar profile")
    return dict(value)


def checked_request(value, *, check_deadline=True):
    expected = {
        "version",
        "run_id",
        "recipe",
        "portrait",
        "audio",
        "observed_input",
        "seed",
        "device_count",
        "deadline_at",
        "permissions",
    }
    if (
        type(value) is not dict
        or set(value) != expected
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError("Invalid fixed whole-recording request")
    if type(value["run_id"]) is not str or str(UUID(value["run_id"])) != value["run_id"]:
        raise ValueError("Use a canonical Run UUID")
    checked_recipe(value["recipe"])
    if (
        type(value["permissions"]) is not list
        or any(type(item) is not str for item in value["permissions"])
        or sorted(value["permissions"]) != ["filesystem_read", "workspace_write"]
    ):
        raise ValueError("Whole-recording portrait read and output write permissions are required")
    if type(value["seed"]) is not int or not 0 <= value["seed"] <= 2147483647:
        raise ValueError("Invalid frozen avatar seed")
    if type(value["device_count"]) is not int or value["device_count"] not in {1, 2}:
        raise ValueError("Choose one or two explicitly allocated GPUs")
    if (
        type(value["deadline_at"]) not in {int, float}
        or not math.isfinite(value["deadline_at"])
        or value["deadline_at"] <= 0
        or check_deadline
        and not 0 < value["deadline_at"] - time.time() <= 14400
    ):
        raise ValueError("Whole-recording deadline must be within the next four hours")
    observation = value["observed_input"]
    fields = {
        "width",
        "height",
        "samples",
        "sample_rate",
        "channels",
        "sample_width",
        "target_frames",
        "base_frames",
        "endpoint_frames",
    }
    if (
        type(observation) is not dict
        or set(observation) != fields
        or any(type(v) is not int for v in observation.values())
    ):
        raise ValueError("Freeze the complete portrait and PCM observation")
    timing = WholeAvatarTiming(observation["samples"], observation["sample_rate"])
    if (
        observation["target_frames"] != timing.target_frames
        or observation["base_frames"] != timing.base_frames
        or observation["endpoint_frames"] != timing.endpoint_frames
        or observation["channels"] not in {1, 2}
        or observation["sample_width"] not in {1, 2, 3, 4}
        or any(not 192 <= observation[key] <= 768 or observation[key] % 64 for key in ("width", "height"))
        or observation["width"] * observation["height"] > 512 * 768
    ):
        raise ValueError("Unqualified whole-recording geometry or timing")
    return value


def checked_media(root, value):
    if (
        type(value) is not dict
        or set(value) != {"relative_path", "size_bytes", "sha256"}
        or type(value["relative_path"]) is not str
        or not value["relative_path"].startswith("artifacts/")
        or type(value["size_bytes"]) is not int
        or not 1 <= value["size_bytes"] <= 20 * 1024**2
        or type(value["sha256"]) is not str
        or re.fullmatch("[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise ValueError("Choose a bounded observed portrait or canonical PCM recording")
    path = direct_file(root, value["relative_path"])
    if (
        path.stat().st_nlink != 1
        or path.stat().st_size != value["size_bytes"]
        or digest(path) != value["sha256"]
    ):
        raise ValueError("Avatar source bytes changed")
    return path


def inspect_inputs(root, portrait, audio):
    from PIL import Image, ImageOps

    portrait_path, audio_path = checked_media(root, portrait), checked_media(root, audio)
    with Image.open(portrait_path) as image:
        if image.format not in {"PNG", "JPEG"}:
            raise ValueError("Choose an intact PNG/JPEG portrait")
        # Bound decoding before EXIF transpose or loading the image's pixels.
        portrait_canvas(*image.size, max_side=768)
        image.verify()
    with Image.open(portrait_path) as image:
        width, height = whole_portrait_canvas(*ImageOps.exif_transpose(image).size)
    with wave.open(str(audio_path), "rb") as source:
        samples, rate, channels, sample_width = (
            source.getnframes(),
            source.getframerate(),
            source.getnchannels(),
            source.getsampwidth(),
        )
        timing = WholeAvatarTiming(samples, rate)
        if channels not in {1, 2} or sample_width not in {1, 2, 3, 4} or source.getcomptype() != "NONE":
            raise ValueError("Choose canonical PCM WAV speech")
        if len(source.readframes(samples)) != samples * channels * sample_width:
            raise ValueError("Truncated canonical PCM recording")
    return {
        "width": width,
        "height": height,
        "samples": samples,
        "sample_rate": rate,
        "channels": channels,
        "sample_width": sample_width,
        "target_frames": timing.target_frames,
        "base_frames": timing.base_frames,
        "endpoint_frames": timing.endpoint_frames,
    }
