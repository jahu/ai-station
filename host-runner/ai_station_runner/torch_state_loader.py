"""Map admitted immutable tensor bytes inside an owned offline inference child.

No torch/pickle deserialization is used. Call only after a fixed runtime profile
has selected its own expected graph/version fingerprints and process limits.
"""

import hashlib
import math
import mmap
import os
import re
import stat
from collections import OrderedDict
from pathlib import Path

from ai_station_runner.torch_state_zip import MAX_FILE, read_archive


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def load_weights(path, *, sha256, size_bytes, mtime, schema_sha256, module_metadata_sha256):
    if (
        any(
            type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in (sha256, schema_sha256, module_metadata_sha256)
        )
        or type(size_bytes) is not int
        or not 128 <= size_bytes <= MAX_FILE
        or type(mtime) not in {float, int}
        or not math.isfinite(mtime)
        or mtime < 0
    ):
        raise ValueError("Use the fixed verified tensor-source observation")
    path = Path(path).absolute()
    if (
        path.name != sha256
        or path.parent.name != "store"
        or path.parent.parent.name != "models"
        or path.resolve(strict=True) != path
    ):
        raise ValueError("Selected tensor weights require an immutable owned model object")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o222
            or before.st_size != size_bytes
            or abs(before.st_mtime - mtime) > 0.001
        ):
            raise ValueError("The immutable selected tensor object changed")
        digest = hashlib.sha256()
        for block in iter(lambda: handle.read(1024**2), b""):
            digest.update(block)
        if digest.hexdigest() != sha256:
            raise ValueError("Selected tensor bytes failed SHA-256")
        parsed = read_archive(handle)
        report = parsed["report"]
        if (
            report["schema_sha256"] != schema_sha256
            or report["module_metadata_sha256"] != module_metadata_sha256
            or not report["storage_layout_verified"]
        ):
            raise ValueError("Selected tensors do not match the fixed graph and module-version data")
        if _identity(before) != _identity(os.fstat(handle.fileno())) or _identity(before) != _identity(
            path.stat()
        ):
            raise ValueError("Selected tensor identity changed during verification")
        import torch

        # Private copy-on-write mapping mirrors legacy mmap loading without
        # permitting inference mutations to write into the immutable object.
        # torch.frombuffer retains the mapping owner for each tensor's lifetime;
        # never close it underneath a live tensor/view.
        mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_COPY)
        dtypes = {"F32": torch.float32, "F16": torch.float16}
        tensors = OrderedDict()
        for value in parsed["tensors"]:
            tensor = torch.frombuffer(
                mapping,
                dtype=dtypes[value["dtype"]],
                count=math.prod(value["shape"]),
                offset=value["data_offset"],
            ).reshape(tuple(value["shape"]))
            tensors[value["name"]] = tensor
        tensors._metadata = parsed["module_versions"]
        return tensors
