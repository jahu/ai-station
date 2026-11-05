"""Pinned HF SafeTensors header ranges; no model payload or publisher code."""

import hashlib
import json
import math
import struct

from app.hub_sources import COMMIT, parse_source
from app.model_download_files import _wait, response
from app.model_setup import fingerprint

HEADER_BUDGET = 32 * 1024**2
STORAGE = {
    "F16": 2,
    "BF16": 2,
    "F32": 4,
    "F64": 8,
    "F8_E4M3": 1,
    "F8_E5M2": 1,
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
            raise ValueError("Duplicate checkpoint header key")
        result[key] = value
    return result


async def read_range(file, begin, end, check):
    source = parse_source(file["source_url"])
    if not source.filename or not COMMIT.fullmatch(source.revision):
        raise ValueError("Checkpoint metadata needs one immutable HF file")
    size = end - begin + 1
    async with response(file["source_url"], begin, check, end=end) as reply:
        if (
            reply.status_code != 206
            or reply.headers.get("content-range") != f"bytes {begin}-{end}/{file['size_bytes']}"
            or reply.headers.get("content-encoding", "identity") != "identity"
            or reply.headers.get("content-length") not in {None, str(size)}
        ):
            raise ValueError("Publisher did not provide the exact bounded checkpoint metadata range")
        data = bytearray()
        chunks = reply.aiter_raw(chunk_size=min(size, 65536)).__aiter__()
        while len(data) < size:
            try:
                chunk = await _wait(check, anext(chunks), 35)
            except StopAsyncIteration:
                raise ValueError("Truncated checkpoint metadata range") from None
            if len(data) + len(chunk) > size:
                raise ValueError("Checkpoint metadata range exceeded its bound")
            data.extend(chunk)
        check()
        return bytes(data)


def describe(raw, file_size):
    if not raw.startswith(b"{") or not 2 <= len(raw) <= HEADER_BUDGET or len(raw) + 8 > file_size:
        raise ValueError("Invalid bounded checkpoint header")
    try:
        header = json.loads(raw, object_pairs_hook=unique_object)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid checkpoint header JSON") from exc
    if not isinstance(header, dict):
        raise ValueError("The checkpoint header must be an object")
    metadata = header.pop("__metadata__", {})
    if not isinstance(metadata, dict) or any(not isinstance(v, str) for v in metadata.values()):
        raise ValueError("Checkpoint metadata must contain strings only")
    for value in (*header, *metadata, *metadata.values()):
        value.encode("utf-8")
    if not 1 <= len(header) <= 100000:
        raise ValueError("Checkpoint tensor count exceeds its metadata bound")
    shapes, dtypes, spans = {}, set(), []
    for name, value in header.items():
        if (
            not name
            or len(name) > 256
            or "\0" in name
            or not isinstance(value, dict)
            or set(value) != {"shape", "dtype", "data_offsets"}
        ):
            raise ValueError("Invalid checkpoint descriptor")
        name.encode("utf-8")
        shape, dtype, offsets = value["shape"], value["dtype"], value["data_offsets"]
        if (
            not isinstance(shape, list)
            or len(shape) > 8
            or any(type(v) is not int or not 0 <= v <= 2**32 for v in shape)
        ):
            raise ValueError("Invalid checkpoint shape")
        if (
            not isinstance(dtype, str)
            or dtype not in STORAGE
            or not isinstance(offsets, list)
            or len(offsets) != 2
            or any(type(v) is not int or v < 0 for v in offsets)
        ):
            raise ValueError("Unsupported checkpoint storage descriptor")
        begin, end = offsets
        if end - begin != math.prod(shape) * STORAGE[dtype] or end > file_size - len(raw) - 8:
            raise ValueError("Checkpoint storage extent differs from its shape")
        shapes[name] = shape
        dtypes.add(dtype)
        spans.append((begin, end))
    cursor = 0
    for begin, end in sorted(spans):
        if begin != cursor:
            raise ValueError("Checkpoint storage contains holes or overlapping tensors")
        cursor = end
    if cursor != file_size - len(raw) - 8:
        raise ValueError("Checkpoint payload is not fully indexed")
    return {
        "schema_sha256": fingerprint(shapes),
        "tensor_count": len(shapes),
        "dtypes": sorted(dtypes),
        "header_sha256": hashlib.sha256(raw).hexdigest(),
        "header_bytes": len(raw) + 8,
    }


async def inspect(file, check):
    size = file.get("size_bytes")
    if (
        not file.get("identity_available")
        or file.get("format") != "safetensors"
        or type(size) is not int
        or size <= 10
    ):
        raise ValueError("Choose one immutable complete SafeTensors file")
    prefix = await read_range(file, 0, 7, check)
    length = struct.unpack("<Q", prefix)[0]
    if not 2 <= length <= HEADER_BUDGET or length + 8 > size:
        raise ValueError("Checkpoint header length exceeds its bound")
    raw = await read_range(file, 8, length + 7, check)
    return describe(raw, size)
