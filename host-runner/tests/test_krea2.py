import hashlib
from types import SimpleNamespace

import pytest
from ai_station_runner.krea2 import KreaFile, KreaOptions, gpu_only_args, require_gpu_placement
from pydantic import ValidationError


@pytest.mark.parametrize(
    "mode,count,role,strength",
    [("t2i", 0, None, None), ("img2img", 1, "general", 4), ("recompose", 2, "identity", 2)],
)
def test_fixed_operation_contract(mode, count, role, strength):
    request = KreaOptions(mode=mode, prompt="A fully clothed person in a garden")
    request.validate_references(count)
    assert request.lora_role() == role
    assert request.reference_strength == strength


@pytest.mark.parametrize(
    "mode,count", [("t2i", 1), ("img2img", 0), ("img2img", 2), ("recompose", 0), ("recompose", 3)]
)
def test_no_silently_dropped_references(mode, count):
    with pytest.raises(ValueError, match="reference count"):
        KreaOptions(mode=mode, prompt="neutral scene").validate_references(count)


@pytest.mark.parametrize(
    "values",
    [
        {"width": 2048, "height": 2048},
        {"cfg": float("nan")},
        {"workflow": {}},
        {"offload": "cpu"},
        {"reference_strength": 2},
    ],
)
def test_unsupported_options_fail_closed(values):
    with pytest.raises(ValidationError):
        KreaOptions(mode="t2i", prompt="neutral scene", **values)


def test_native_arguments_never_enable_cpu_or_layer_streaming(tmp_path):
    args = gpu_only_args(tmp_path)
    assert "--gpu-only" in args
    assert "--disable-dynamic-vram" in args
    assert "--disable-async-offload" in args
    assert "--offline" in args
    assert not set(args) & {"--cpu", "--cpu-vae", "--lowvram", "--novram", "--fast-disk"}


def test_unexpected_runtime_cpu_offload_is_rejected():
    require_gpu_placement(SimpleNamespace(load_device="cuda:1", offload_device="cuda:1"), 1)
    for load, offload in [("cuda:1", "cpu"), ("cpu", "cuda:1"), ("cuda:0", "cuda:0")]:
        with pytest.raises(ValueError, match="GPU-only placement"):
            require_gpu_placement(SimpleNamespace(load_device=load, offload_device=offload), 1)


def test_selected_weight_hash_is_required_and_mutations_are_rejected(tmp_path):
    path = tmp_path / "model.gguf"
    path.write_bytes(b"verified")
    file = KreaFile(path=str(path), size=8, sha256=hashlib.sha256(b"verified").hexdigest())
    assert file.verify() == path
    path.write_bytes(b"modified")
    with pytest.raises(ValueError, match="SHA-256"):
        file.verify()
    path.unlink()
    with pytest.raises(ValueError, match="missing"):
        file.verify()
