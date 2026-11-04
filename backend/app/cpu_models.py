"""Explicit small-model CPU presets; the Runner rechecks actual GGUF geometry."""


def estimate(entry):
    per_token = (
        entry.attention_layers * entry.kv_heads * ((entry.key_length // 32) + (entry.value_length // 32)) * 34
    )
    total = (
        (entry.file.size_bytes * 115 + 99) // 100
        + 4096 * per_token
        + (1024 + entry.state_reserve_mib) * 1024**2
    )
    return (total + 1024**2 - 1) // 1024**2


def fields(values):
    return {
        key: values[key]
        for key in ("runtime_profile", "ram_mib", "environment_id")
        if values.get(key) is not None
    }


def compatible(definition, entry):
    return (definition.metadata_json or {}).get("runtime_profile") == entry.runtime_profile
