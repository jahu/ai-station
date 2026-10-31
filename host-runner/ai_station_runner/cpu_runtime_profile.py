"""Fixed CPU conversation profile; no implicit fallback from CUDA execution."""

PROFILE = "llamacpp-cpu-linux-amd64-v1"
REFERENCE = (
    "ghcr.io/ggml-org/llama.cpp@sha256:c50671c463e746cdccf2c6e77ffd6d77dca2e95290e54ca5ba5c7f524c33e234"
)
SOURCE_REVISION = "1052f7e1d62611d328ccc65d38c77cd194ee59fc"
QUALIFIED = True
DEFAULT_CONTEXT = 4096
MIB = 1024**2


def memory_budget_mib(size_bytes, context_size, context_profile):
    """Weight loading, complete Q8 KV/state and a separate one-GiB runtime margin.

    This initial small-model profile deliberately bounds weights and context.
    Admission must additionally observe available RAM and reserve it durably;
    this estimate alone never authorizes a container launch or marks readiness.
    """
    if (
        type(size_bytes) is not int
        or not 0 < size_bytes <= 8 * 1024**3
        or type(context_size) is not int
        or not 512 <= context_size <= 32768
        or context_size % 256
        or not isinstance(context_profile, dict)
        or context_profile.get("source") != "gguf_header"
    ):
        raise ValueError("Use an inspected small model and bounded CPU context")
    per_token = context_profile.get("q8_kv_bytes_per_token")
    trained = context_profile.get("trained_context")
    reserve = context_profile.get("state_reserve_mib", 0)
    if (
        type(per_token) is not int
        or not 1 <= per_token <= 16 * MIB
        or type(trained) is not int
        or not context_size <= trained <= 16777216
        or type(reserve) is not int
        or not 0 <= reserve <= 4096
    ):
        raise ValueError("The inspected CPU cache/state dimensions are invalid")
    # Integer arithmetic rounds upward, including the 15% weight-load margin.
    weight_loading = (size_bytes * 115 + 99) // 100
    total = weight_loading + context_size * per_token + (reserve + 1024) * MIB
    return (total + MIB - 1) // MIB


def recipe():
    return {
        "profile": PROFILE,
        "name": "llama.cpp · Local CPU",
        "image_reference": REFERENCE,
        "platform": "linux/amd64",
        "license": "MIT (llama.cpp); bundled base-system licenses",
        "license_url": "https://github.com/ggml-org/llama.cpp/blob/" + SOURCE_REVISION + "/LICENSE",
        "download_bytes": 309482267,
        "minimum_free_bytes": 2 * 1024**3,
        "layers": {
            "7a48b8f0e5c73d0cc2a85b008978396aa19d253dc1b96fdb0b769ee6dcbeca4a": 29767612,
            "51d0a056c3fd1f909b87dabf8b0f1f3895c5b79880ce542d058ab6206407edfa": 260756536,
            "527deae2828283e77e80a5d30514c47c0db65e9de03d80e1aa9319b5c8221701": 18932939,
            "4c96f76f36994b1b68ba648e5afbd441f36c21c7e97aa77df09da749bafcfe9b": 25148,
            "4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1": 32,
        },
        "capability": "chat",
        "source_url": "https://github.com/ggml-org/llama.cpp/tree/" + SOURCE_REVISION,
        "qualification": "CPU candidate; fixed small GGUF; 4096-token Q8 cache",
        "compute_target": "cpu",
    }
