"""Bounded SafeTensors descriptors; no tensor payload, framework or model code."""

import json
import math
import os
import stat
import struct

HEADER_BUDGET = 32 * 1024**2
# Only these byte-addressable representations are admitted by this reader.
STORAGE = {
    "F64": 8,
    "F32": 4,
    "F16": 2,
    "BF16": 2,
    "I64": 8,
    "I32": 4,
    "I16": 2,
    "I8": 1,
    "U64": 8,
    "U32": 4,
    "U16": 2,
    "U8": 1,
    "BOOL": 1,
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate SafeTensors JSON key")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("Non-finite JSON is not a SafeTensors descriptor")


def inspect_header(path, size_bytes, mtime):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size != size_bytes
            or abs(before.st_mtime - mtime) > 0.001
        ):
            raise ValueError("Model changed since discovery")
        prefix = handle.read(8)
        if len(prefix) != 8:
            raise ValueError("Truncated SafeTensors length")
        length = struct.unpack("<Q", prefix)[0]
        if not 2 <= length <= HEADER_BUDGET or length + 8 > size_bytes:
            raise ValueError("SafeTensors header budget or extent exceeded")
        raw = handle.read(length)
        if len(raw) != length or not raw.startswith(b"{"):
            raise ValueError("Invalid SafeTensors header")
        try:
            header = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        except (UnicodeError, RecursionError) as exc:
            raise ValueError("Invalid bounded SafeTensors JSON") from exc
        if not isinstance(header, dict):
            raise ValueError("SafeTensors descriptors must be an object")
        metadata = header.pop("__metadata__", {})
        if not isinstance(metadata, dict) or any(not isinstance(v, str) for v in metadata.values()):
            raise ValueError("SafeTensors metadata must contain strings only")
        try:
            for value in (*header, *metadata, *metadata.values()):
                value.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("SafeTensors strings must be valid Unicode") from exc
        if not 1 <= len(header) <= 100000:
            raise ValueError("SafeTensors tensor descriptor budget exceeded")
        tensors = []
        for name, tensor in header.items():
            if not name or len(name) > 256 or "\0" in name or not isinstance(tensor, dict):
                raise ValueError("Invalid SafeTensors tensor name or descriptor")
            if set(tensor) != {"dtype", "shape", "data_offsets"}:
                raise ValueError("Unexpected SafeTensors descriptor fields")
            dtype, shape, offsets = tensor["dtype"], tensor["shape"], tensor["data_offsets"]
            if not isinstance(dtype, str) or dtype not in STORAGE:
                raise ValueError("Unsupported SafeTensors storage type")
            if (
                not isinstance(shape, list)
                or len(shape) > 8
                or any(type(v) is not int or not 0 <= v <= 2**32 for v in shape)
            ):
                raise ValueError("Invalid SafeTensors tensor shape")
            if (
                not isinstance(offsets, list)
                or len(offsets) != 2
                or any(type(v) is not int or v < 0 for v in offsets)
            ):
                raise ValueError("Invalid SafeTensors offsets")
            begin, end = offsets
            if end - begin != math.prod(shape) * STORAGE[dtype] or end > size_bytes - 8 - length:
                raise ValueError("SafeTensors tensor extent differs from its storage shape")
            tensors.append({"name": name, "shape": shape, "dtype": dtype, "offsets": offsets})
        cursor = 0
        for tensor in sorted(tensors, key=lambda v: v["offsets"]):
            begin, end = tensor["offsets"]
            if begin != cursor:
                raise ValueError("SafeTensors payload has overlapping tensors or holes")
            cursor = end
        if cursor != size_bytes - 8 - length:
            raise ValueError("SafeTensors payload is truncated or has trailing unindexed bytes")
        after = os.fstat(handle.fileno())
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError("Model changed during inspection")
    return {
        "tensor_count": len(tensors),
        "tensors": tensors,
        "header_bytes": 8 + length,
        "tensor_storage_bytes": cursor,
    }
