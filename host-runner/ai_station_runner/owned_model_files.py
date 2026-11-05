"""Immutable owned model files shared by native children without an HTTP stack."""

import os
import re
import stat
import struct
from pathlib import Path

SHA = re.compile(r"[a-f0-9]{64}\Z")


def verify_owned_model(root, relative, digest, *, checkpoint_format="gguf"):
    if not isinstance(digest, str) or not SHA.fullmatch(digest) or relative != "models/store/" + digest:
        raise ValueError("Choose a verified app-owned model reference")
    if checkpoint_format not in {"gguf", "safetensors", "pytorch_zip_tensor_data"}:
        raise ValueError("Unsupported owned model format")
    root = Path(root).resolve()
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("App-owned models cannot cross symlinks")
    try:
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o222
        ):
            raise ValueError("The model is not an immutable owned regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if checkpoint_format == "safetensors":
                prefix = source.read(8)
                if len(prefix) != 8 or not 2 <= struct.unpack("<Q", prefix)[0] <= 32 * 1024**2:
                    raise ValueError("The model does not have a bounded SafeTensors header")
                if source.read(1) != b"{":
                    raise ValueError("The model does not have a SafeTensors header")
            elif checkpoint_format == "pytorch_zip_tensor_data":
                if source.read(4) != b"PK\x03\x04":
                    raise ValueError("The model does not have a tensor ZIP header")
            elif source.read(4) != b"GGUF":
                raise ValueError("The model does not have a GGUF header")
    except (OSError, ValueError) as exc:
        label = {
            "gguf": "GGUF",
            "safetensors": "SafeTensors checkpoint",
            "pytorch_zip_tensor_data": "tensor ZIP",
        }[checkpoint_format]
        raise ValueError(f"The verified app-owned {label} is unavailable or changed") from exc
    return path
