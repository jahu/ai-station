"""Bounded language-model context inspection through the shared GGUF reader."""

from pathlib import Path

from ai_station_runner.gguf_headers import HEADER_BUDGET as HEADER_BUDGET
from ai_station_runner.gguf_headers import inspect_header

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
    report = inspect_header(
        path,
        size_bytes,
        mtime,
        keep_field=lambda key: key == "general.architecture" or key.partition(".")[2] in _FIELDS,
    )
    return context_profile(report["fields"])


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
