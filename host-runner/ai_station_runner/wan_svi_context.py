"""Closed SVI Pro context primitives; not an operational executor registration.

Wan21 uses 16 latent channels and an original anchor on every window. Its
single preceding motion latent must never enter the existing 48-channel 5B path.
The complete model/anchor/implementation identity is supplied by native dispatch.
"""

import json
import re
import struct

WIDTH = 832
HEIGHT = 480
FRAMES = 81
FPS = 15
CONTEXT_FRAMES = 4
MAX_BYTES = 512 * 1024
METADATA_KEY = "station.svi_profile"
SHAPE = (1, 16, 1, HEIGHT // 8, WIDTH // 8)


def generation_dimensions(profile="landscape"):
    if type(profile) is not str or profile not in {"landscape", "portrait"}:
        raise ValueError("Choose a fixed SVI generation profile")
    return (WIDTH, HEIGHT) if profile == "landscape" else (HEIGHT, WIDTH)


def motion_shape(width=WIDTH, height=HEIGHT):
    """Finite geometry only; this primitive does not qualify a native format."""
    if (
        type(width) is not int
        or type(height) is not int
        or (width, height) not in {(WIDTH, HEIGHT), (HEIGHT, WIDTH)}
    ):
        raise ValueError("SVI context requires a fixed landscape or portrait geometry")
    return (1, 16, 1, height // 8, width // 8)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate SVI checkpoint header key")
        result[key] = value
    return result


def validate_checkpoint(path, expected_profile, *, width=WIDTH, height=HEIGHT):
    """Read only a bounded non-executable tensor header before tensor loading.

    Callers retain canonical owned-path and complete content-hash validation.
    This check additionally binds latent geometry to the frozen recipe/anchor.
    Private experimental checkpoints have a different metadata key and refuse.
    """
    shape = motion_shape(width, height)
    if not isinstance(expected_profile, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_profile):
        raise ValueError("SVI context requires its complete frozen profile identity")
    if path.is_symlink() or not path.is_file():
        raise ValueError("SVI context must be an owned regular file")
    with path.open("rb") as source:
        prefix = source.read(8)
        if len(prefix) != 8:
            raise ValueError("Invalid bounded SVI checkpoint header")
        length = struct.unpack("<Q", prefix)[0]
        if not 0 < length <= 8192:
            raise ValueError("Invalid bounded SVI checkpoint header")
        raw = source.read(length)
        if len(raw) != length:
            raise ValueError("Truncated SVI checkpoint header")
        header = json.loads(raw, object_pairs_hook=_unique_object)
        source.seek(0, 2)
        size = source.tell()
    if not 8 < size <= MAX_BYTES:
        raise ValueError("SVI checkpoint exceeds its bounded tensor budget")
    if not isinstance(header, dict) or set(header) != {"motion", "__metadata__"}:
        raise ValueError("Unexpected tensors in SVI checkpoint")
    tensor, metadata = header["motion"], header["__metadata__"]
    payload_bytes = 16 * shape[-2] * shape[-1] * 4
    if (
        not isinstance(tensor, dict)
        or set(tensor) != {"dtype", "shape", "data_offsets"}
        or tensor.get("dtype") != "F32"
        or not isinstance(tensor.get("shape"), list)
        or any(type(value) is not int for value in tensor["shape"])
        or tensor["shape"] != list(shape)
        or not isinstance(tensor.get("data_offsets"), list)
        or any(type(value) is not int for value in tensor["data_offsets"])
        or tensor["data_offsets"] != [0, payload_bytes]
        or size != 8 + length + payload_bytes
        or not isinstance(metadata, dict)
        or set(metadata) != {METADATA_KEY}
        or metadata[METADATA_KEY] != expected_profile
    ):
        raise ValueError("SVI motion geometry or frozen profile changed")
    return shape


def conditioning(anchor, previous, latent_format, *, width=WIDTH, height=HEIGHT):
    """Build raw-core conditioning equivalent to the pinned Pro embedder.

    The core applies latent normalization itself. Raw zero is therefore *not*
    neutral padding: represent normalized zero through process_out first. The
    anchor stays at index zero; prior motion, when present, occupies index one.
    Its mask intentionally differs from a second image anchor.
    """
    import torch

    shape = motion_shape(width, height)
    if tuple(anchor.shape) != shape or (previous is not None and tuple(previous.shape) != shape):
        raise ValueError("SVI context must match its fixed Wan21 anchor geometry")
    if (
        anchor.dtype != torch.float32
        or not torch.isfinite(anchor).all()
        or (
            previous is not None
            and (
                previous.dtype != anchor.dtype
                or previous.device != anchor.device
                or not torch.isfinite(previous).all()
            )
        )
    ):
        raise ValueError("SVI context requires finite matching F32 tensors")
    count = (FRAMES - 1) // 4 + 1
    normalized = torch.zeros((1, 16, count, *shape[-2:]), dtype=anchor.dtype, device=anchor.device)
    raw = latent_format.process_out(normalized)
    raw[:, :, :1] = anchor
    if previous is not None:
        raw[:, :, 1:2] = previous
    mask = torch.ones((1, 1, count, *shape[-2:]), dtype=anchor.dtype, device=anchor.device)
    mask[:, :, :1] = 0
    return raw, mask
