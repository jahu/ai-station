import pytest
from ai_station_runner import cpu_runtime_profile as cpu


def profile(**changes):
    return {
        "source": "gguf_header",
        "trained_context": 131072,
        "q8_kv_bytes_per_token": 65536,
        "state_reserve_mib": 512,
        **changes,
    }


def test_cpu_candidate_is_fixed_and_unavailable_before_lifecycle_qualification():
    assert cpu.QUALIFIED is False
    assert cpu.PROFILE == "llamacpp-cpu-linux-amd64-v1"
    assert cpu.REFERENCE.startswith("ghcr.io/ggml-org/llama.cpp@sha256:")
    assert cpu.DEFAULT_CONTEXT == 4096


def test_cpu_budget_includes_weights_full_cache_recurrent_state_and_load_margin():
    # 2 GiB weights * 1.15 + 256 MiB KV + 512 MiB state + 1 GiB runtime.
    assert cpu.memory_budget_mib(2 * 1024**3, 4096, profile()) == 4148
    assert cpu.memory_budget_mib(2 * 1024**3, 8192, profile()) == 4404
    assert cpu.memory_budget_mib(2 * 1024**3, 4096, profile(state_reserve_mib=0)) == 3636


@pytest.mark.parametrize("size", [True, 0, -1, float("inf"), 8 * 1024**3 + 1])
def test_cpu_candidate_rejects_unbounded_weight_sizes(size):
    with pytest.raises(ValueError):
        cpu.memory_budget_mib(size, 4096, profile())


@pytest.mark.parametrize("context", [True, 0, -1, 500, 4097, 33024, float("nan")])
def test_cpu_candidate_rejects_invalid_or_out_of_profile_context(context):
    with pytest.raises(ValueError):
        cpu.memory_budget_mib(2 * 1024**3, context, profile())


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "filename_guess"},
        {"trained_context": 2048},
        {"trained_context": True},
        {"q8_kv_bytes_per_token": 0},
        {"q8_kv_bytes_per_token": float("inf")},
        {"q8_kv_bytes_per_token": 16 * cpu.MIB + 1},
        {"state_reserve_mib": -1},
        {"state_reserve_mib": True},
        {"state_reserve_mib": 4097},
    ],
)
def test_cpu_candidate_rejects_unknown_or_changed_cache_geometry(changes):
    with pytest.raises(ValueError):
        cpu.memory_budget_mib(2 * 1024**3, 4096, profile(**changes))
