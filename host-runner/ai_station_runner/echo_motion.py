"""Bounded non-executable EchoMimic temporal conditioning checkpoints."""

import hashlib
import json
import math
import struct
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024


def profile_key(runtime, models):
    base = Path(models) / "Wan2.1-Fun-V1.1-1.3B-InP"
    paths = {
        "config": Path(runtime) / "config/config.yaml",
        "transformer": Path(models) / "transformer/diffusion_pytorch_model.safetensors",
        "vae": base / "Wan2.1_VAE.pth",
        "text_encoder": base / "models_t5_umt5-xxl-enc-bf16.pth",
        "identity_encoder": base / "models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
    }
    observed = {
        key: {"size_bytes": path.stat().st_size, "mtime": path.stat().st_mtime} for key, path in paths.items()
    }
    return hashlib.sha256(json.dumps({"version": 2, "files": observed}, sort_keys=True).encode()).hexdigest()


def validate_checkpoint(path, size, profile):
    length = path.stat().st_size
    if not 8 < length <= MAX_BYTES:
        raise ValueError("Avatar motion checkpoint exceeds its tensor budget")
    with path.open("rb") as source:
        header_size = struct.unpack("<Q", source.read(8))[0]
        if not 0 < header_size <= 8192 or header_size + 8 > length:
            raise ValueError("Invalid avatar motion header")
        header = json.loads(source.read(header_size))
    if not isinstance(header, dict) or set(header) != {"motion", "__metadata__"}:
        raise ValueError("Unexpected avatar motion tensors")
    tensor, metadata = header["motion"], header["__metadata__"]
    if not isinstance(tensor, dict) or not isinstance(tensor.get("shape"), list) or len(tensor["shape"]) != 5:
        raise ValueError("Invalid avatar motion tensor shape")
    groups = tensor["shape"][2]
    if type(groups) is not int or not 5 <= groups <= 21:
        raise ValueError("Avatar motion history exceeds its temporal budget")
    shape = [1, 16, groups, size // 8, size // 8]
    payload = 16 * groups * (size // 8) ** 2 * 4
    if (
        not isinstance(tensor, dict)
        or not isinstance(metadata, dict)
        or tensor.get("dtype") != "F32"
        or tensor.get("shape") != shape
        or any(type(v) is not int for v in tensor.get("shape", []))
        or tensor.get("data_offsets") != [0, payload]
        or length != 8 + header_size + payload
        or metadata.get("station.echo_profile") != profile
    ):
        raise ValueError("Avatar motion shape or model observation changed")
    return shape


def flow_sigma(scheduler, index):
    if type(scheduler).__name__ not in {
        "FlowMatchEulerDiscreteScheduler",
        "FlowUniPCMultistepScheduler",
        "FlowDPMSolverMultistepScheduler",
    }:
        raise ValueError("Avatar continuation requires the configured flow scheduler")
    if type(index) is not int or not 0 <= index < len(scheduler.sigmas):
        raise ValueError("Invalid avatar continuation noise step")
    value = float(scheduler.sigmas[index])
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Invalid avatar continuation noise level")
    return value
