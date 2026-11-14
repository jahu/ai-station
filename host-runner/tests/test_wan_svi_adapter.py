"""Finite publisher layout and logical GGUF geometry, without AI dependencies."""

from types import SimpleNamespace

import pytest
from ai_station_runner.wan_svi_adapter import target_map


def weights():
    result = {}
    for block in range(40):
        for layer in (
            "self_attn.q",
            "self_attn.k",
            "self_attn.v",
            "self_attn.o",
            "cross_attn.q",
            "cross_attn.k",
            "cross_attn.v",
            "cross_attn.o",
            "ffn.0",
            "ffn.2",
        ):
            result[f"blocks.{block}.{layer}.lora_A.default.weight"] = SimpleNamespace(shape=(128, 5120))
            result[f"blocks.{block}.{layer}.lora_B.default.weight"] = SimpleNamespace(shape=(5120, 128))
    return result


def test_complete_pro_layout_maps_all_blocks_to_core_diffusion_parameters():
    observed = []

    def logical_shape(key):
        observed.append(key)
        return (5120, 5120)

    mapping = target_map(weights(), logical_shape)
    assert len(mapping) == len(set(observed)) == 400
    assert mapping["blocks.39.ffn.2"] == "diffusion_model.blocks.39.ffn.2.weight"
    assert mapping["blocks.0.cross_attn.q"] == "diffusion_model.blocks.0.cross_attn.q.weight"


def test_packed_meta_shape_is_not_valid_logical_matrix_geometry():
    with pytest.raises(ValueError, match="logical target geometry"):
        target_map(weights(), lambda key: (5120 * 5120 // 2,))


@pytest.mark.parametrize("shape", [(5120, 4096), (0, 5120), (True, 5120)])
def test_changed_base_geometry_is_rejected(shape):
    with pytest.raises(ValueError, match="geometry"):
        target_map(weights(), lambda key: shape)


def test_changed_rank_cannot_silently_apply_to_a_subset_of_layers():
    values = weights()
    values["blocks.39.ffn.2.lora_B.default.weight"].shape = (5120, 64)
    with pytest.raises(ValueError, match="geometry"):
        target_map(values, lambda key: (5120, 5120))


@pytest.mark.parametrize("mutation", ["missing", "extra", "unknown_layer"])
def test_missing_or_unrecognized_adapter_targets_fail_before_model_access(mutation):
    values = weights()
    if mutation == "missing":
        del values["blocks.0.self_attn.q.lora_A.default.weight"]
    elif mutation == "extra":
        values["arbitrary.weight"] = SimpleNamespace(shape=(1, 1))
    else:
        value = values.pop("blocks.39.ffn.2.lora_A.default.weight")
        values["blocks.40.ffn.2.lora_A.default.weight"] = value

    def forbidden(key):
        raise AssertionError("Bad target layout reached model access")

    with pytest.raises(ValueError, match="target layout"):
        target_map(values, forbidden)
