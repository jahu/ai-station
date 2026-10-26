"""Bounded non-executable Wan motion checkpoints; no torch/pickle in validation."""

import hashlib
import json
import struct
from pathlib import Path

MAX_BYTES = 4 * 1024 * 1024


def continuation_pixels(path, sha256, width, height, context_frames=17):
    """Verify and decode the exact bounded RGB prefix for the next native window."""
    from collections import deque

    import av
    import numpy as np

    if type(context_frames) is not int or context_frames not in (1, 17):
        raise ValueError("Unsupported bounded continuation prefix")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha256:
        raise ValueError("Continuation segment content changed")
    prior = deque(maxlen=context_frames)
    with av.open(str(path)) as container:
        for count, frame in enumerate(container.decode(video=0), start=1):
            if frame.width != width or frame.height != height:
                raise ValueError("Continuation segment dimensions changed")
            if count > 81:
                raise ValueError("Continuation input exceeds native segment size")
            prior.append(frame.to_ndarray(format="rgb24"))
    if len(prior) < context_frames:
        raise ValueError("Continuation does not contain its required preceding frames")
    return np.stack(list(prior)).astype(np.float32) / 255


def profile_key(paths, memory_profile="default", guidance="standard"):
    observed = {
        key: {"size_bytes": Path(paths[key]).stat().st_size, "mtime": Path(paths[key]).stat().st_mtime}
        for key in ("wan_model", "wan_text_encoder", "wan_vae")
    }
    # Old checkpoints must keep their exact identity. Alternative loading
    # profiles cannot silently consume or publish a default-precision checkpoint.
    identity = (
        observed if memory_profile == "default" else {"models": observed, "memory_profile": memory_profile}
    )
    if guidance != "standard":
        from ai_station_runner.wan_guidance import apg_observation

        observation = apg_observation(paths)
        if guidance != "apg_v1" or observation is None:
            raise ValueError("Unsupported fixed Wan guidance checkpoint profile")
        identity = {
            "models": observed,
            "memory_profile": memory_profile,
            "guidance": guidance,
            "guidance_source": observation,
        }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_checkpoint(path, width, height, expected_profile):
    size = path.stat().st_size
    if not 8 < size <= MAX_BYTES:
        raise ValueError("Motion checkpoint exceeds its bounded tensor budget")
    with path.open("rb") as source:
        length = struct.unpack("<Q", source.read(8))[0]
        if not 0 < length <= 8192 or length + 8 > size:
            raise ValueError("Invalid bounded motion header")
        header = json.loads(source.read(length))
    if not isinstance(header, dict) or set(header) != {"motion", "__metadata__"}:
        raise ValueError("Unexpected tensors in motion checkpoint")
    tensor = header["motion"]
    if not isinstance(tensor, dict) or not isinstance(tensor.get("shape"), list):
        raise ValueError("Invalid motion tensor header")
    shape = [1, 48, 5, height // 16, width // 16]
    payload_bytes = 48 * 5 * (height // 16) * (width // 16) * 4
    if (
        not isinstance(tensor, dict)
        or not isinstance(header["__metadata__"], dict)
        or any(type(value) is not int for value in tensor.get("shape", []))
        or tensor.get("dtype") != "F32"
        or tensor.get("shape") != shape
        or tensor.get("data_offsets") != [0, payload_bytes]
        or size != 8 + length + payload_bytes
        or header["__metadata__"].get("station.wan_profile") != expected_profile
    ):
        raise ValueError("Motion checkpoint shape or model observation changed")
    return shape
