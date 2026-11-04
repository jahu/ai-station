"""Bounded GGUF metadata/descriptors; never read tensor payloads or execute code."""

import os
import stat
import struct
from pathlib import Path

HEADER_BUDGET = 32 * 1024 * 1024
_FORMATS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


def inspect_header(path: Path, size_bytes: int, mtime: float, *, keep_field, tensors=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        observed = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_size != size_bytes
            or abs(observed.st_mtime - mtime) > 0.001
        ):
            raise ValueError("Model changed since discovery")
        budget = min(HEADER_BUDGET, observed.st_size)

        def read(count):
            if count < 0 or handle.tell() + count > budget:
                raise ValueError("GGUF metadata budget exceeded")
            data = handle.read(count)
            if len(data) != count:
                raise ValueError("Truncated GGUF metadata")
            return data

        def integer(fmt):
            return struct.unpack("<" + fmt, read(struct.calcsize(fmt)))[0]

        def skip(count):
            if count < 0 or handle.tell() + count > budget:
                raise ValueError("GGUF metadata budget exceeded")
            handle.seek(count, 1)

        def value(kind, keep=False):
            if kind in _FORMATS:
                return integer(_FORMATS[kind])
            if kind == 8:
                length = integer("Q")
                if keep:
                    if length > 256:
                        raise ValueError("GGUF scalar string is too large")
                    return read(length).decode("utf-8")
                skip(length)
                return None
            if kind == 9:
                item_kind, count = integer("I"), integer("Q")
                if count > 500000 or item_kind == 9:
                    raise ValueError("Unsupported GGUF array")
                if item_kind in _FORMATS:
                    skip(count * struct.calcsize(_FORMATS[item_kind]))
                elif item_kind == 8:
                    for _ in range(count):
                        skip(integer("Q"))
                else:
                    raise ValueError("Unknown GGUF array type")
                return None
            raise ValueError("Unknown GGUF metadata type")

        if read(4) != b"GGUF" or integer("I") not in (2, 3):
            raise ValueError("Unsupported GGUF header")
        tensor_count = integer("Q")
        count = integer("Q")
        if count > 4096:
            raise ValueError("GGUF metadata entry budget exceeded")
        fields = {}
        for _ in range(count):
            key = value(8, True)
            kind = integer("I")
            keep = keep_field(key)
            result = value(kind, keep)
            if keep:
                if key in fields:
                    raise ValueError("Duplicate GGUF context metadata")
                fields[key] = result
        descriptors = []
        if tensors:
            if not 1 <= tensor_count <= 100000:
                raise ValueError("GGUF tensor descriptor budget exceeded")
            names = set()
            for _ in range(tensor_count):
                name = value(8, True)
                if not name or name in names:
                    raise ValueError("Duplicate or empty GGUF tensor name")
                names.add(name)
                dimensions = integer("I")
                if not 1 <= dimensions <= 4:
                    raise ValueError("Unsupported GGUF tensor dimensions")
                shape = [integer("Q") for _ in range(dimensions)]
                if any(not 1 <= size <= 2**32 for size in shape):
                    raise ValueError("Invalid GGUF tensor shape")
                descriptors.append(
                    {"name": name, "shape": shape, "type": integer("I"), "offset": integer("Q")}
                )
        header_bytes = handle.tell()
        after = os.fstat(handle.fileno())
        if after.st_size != observed.st_size or after.st_mtime_ns != observed.st_mtime_ns:
            raise ValueError("Model changed during inspection")
    return {
        "fields": fields,
        "tensor_count": tensor_count,
        "tensors": descriptors,
        "header_bytes": header_bytes,
    }
