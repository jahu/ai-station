"""Bounded GGUF metadata inspection; no tensor reads or third-party dependencies."""

import os
import stat
import struct
from pathlib import Path

HEADER_BUDGET = 32 * 1024 * 1024
_FORMATS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
_FIELDS = {
    "block_count",
    "context_length",
    "embedding_length",
    "attention.head_count",
    "attention.head_count_kv",
    "attention.key_length",
    "attention.value_length",
    "full_attention_interval",
    "attention.recurrent_layers",
}


def inspect_context(path: Path, size_bytes: int, mtime: float) -> dict:
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
        integer("Q")  # Tensor count; tensor descriptors/data are never read.
        count = integer("Q")
        if count > 4096:
            raise ValueError("GGUF metadata entry budget exceeded")
        fields = {}
        for _ in range(count):
            key = value(8, True)
            kind = integer("I")
            keep = key == "general.architecture" or key.partition(".")[2] in _FIELDS
            result = value(kind, keep)
            if keep:
                if key in fields:
                    raise ValueError("Duplicate GGUF context metadata")
                fields[key] = result
        after = os.fstat(handle.fileno())
        if after.st_size != observed.st_size or after.st_mtime_ns != observed.st_mtime_ns:
            raise ValueError("Model changed during inspection")
    return context_profile(fields)


def context_profile(fields: dict) -> dict:
    architecture = fields.get("general.architecture")
    if architecture not in {"llama", "qwen2", "qwen3", "qwen35"}:
        raise ValueError("Architecture has no verified KV estimator")

    def positive(name, default=None, maximum=1048576):
        value = fields.get(architecture + "." + name, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError("Invalid GGUF attention dimensions")
        return value

    layers = positive("block_count", maximum=512)
    heads = positive("attention.head_count", maximum=512)
    kv_heads = positive("attention.head_count_kv", heads, maximum=heads)
    embedding = positive("embedding_length")
    key = positive("attention.key_length", embedding // heads, maximum=4096)
    val = positive("attention.value_length", key, maximum=4096)
    context = positive("context_length", maximum=16777216)
    if context < 512 or key % 32 or val % 32:
        raise ValueError("Unsupported context or quantized cache dimensions")
    reserve = 0
    if architecture == "qwen35":
        if architecture + ".attention.recurrent_layers" in fields:
            raise ValueError("Explicit recurrent-layer arrays require a verified estimator")
        interval = positive("full_attention_interval", maximum=layers)
        layers //= interval
        reserve = 512
    # Q8_0 blocks store 32 values and a 2-byte scale, for each K/V row.
    per_token = layers * kv_heads * (((key + 31) // 32) + ((val + 31) // 32)) * 34
    if not 1 <= per_token <= 16 * 1024 * 1024:
        raise ValueError("Unsupported KV cache dimensions")
    return {
        "source": "gguf_header",
        "architecture": architecture,
        "trained_context": context,
        "attention_layers": layers,
        "q8_kv_bytes_per_token": per_token,
        "state_reserve_mib": reserve,
    }
