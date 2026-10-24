"""The experimental loader must fail closed and never change unrelated loads."""

import json
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest
from ai_station_runner.echo_loading import (
    assign_complete,
    constructor_options,
    mapped_loading,
    qualification_scope,
    transformer_options,
)


def test_transformer_config_mapping_preserves_input_and_constructor_filter(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"in_dim": 36, "dim": 1536}))
    options = {"dict_mapping": {"in_dim": "in_channels", "dim": "hidden_size"}}
    config, mapped = transformer_options(tmp_path, options)
    assert config == {"in_dim": 36, "dim": 1536}
    assert mapped["in_channels"] == 36 and mapped["hidden_size"] == 1536
    assert "in_channels" not in options

    class Model:
        def __init__(self, in_channels):
            pass

    assert constructor_options(Model, mapped) == {"in_channels": 36}


class Model:
    def __init__(self, *, meta=False, incomplete=False):
        self.meta, self.incomplete = meta, incomplete
        self.calls = []

    def load_state_dict(self, state, **kwargs):
        self.calls.append(("load", state, kwargs))
        if self.incomplete:
            raise RuntimeError("Missing checkpoint keys")
        return "complete"

    def parameters(self):
        return iter([SimpleNamespace(is_meta=False)])

    def buffers(self):
        return iter([SimpleNamespace(is_meta=self.meta)])

    def to(self, **kwargs):
        self.calls.append(("to", kwargs))


def test_assign_requires_complete_keys_and_preserves_requested_dtype():
    model = Model()
    assert assign_complete(model, {"weight": 17}, dtype="bf16") == "complete"
    assert model.calls == [
        ("load", {"weight": 17}, {"strict": True, "assign": True}),
        ("to", {"dtype": "bf16"}),
    ]


def test_missing_keys_do_not_fall_back_to_random_initialization():
    model = Model(incomplete=True)
    with pytest.raises(RuntimeError, match="Missing checkpoint"):
        assign_complete(model, {}, dtype="bf16")
    assert len(model.calls) == 1


def test_uninitialized_buffer_cannot_escape_as_a_usable_model():
    model = Model(meta=True)
    with pytest.raises(ValueError, match="uninitialized"):
        assign_complete(model, {}, dtype="bf16")
    assert len(model.calls) == 1


def test_experimental_entry_requires_opt_in_before_any_model_import(monkeypatch):
    monkeypatch.delenv("AI_STATION_REAL_GPU_TESTS", raising=False)
    with pytest.raises(ValueError, match="opt-in"):
        qualification_scope("00000000-0000-0000-0000-000000000000")


def test_opt_in_still_requires_actual_owned_kernel_limits(monkeypatch):
    from ai_station_runner import memory_scope

    calls = []

    def require(run_id, maximum):
        calls.append((run_id, maximum))
        raise ValueError("Outside the private scope")

    monkeypatch.setenv("AI_STATION_REAL_GPU_TESTS", "1")
    monkeypatch.setattr(memory_scope, "require_scope", require)
    with pytest.raises(ValueError, match="private scope"):
        qualification_scope("00000000-0000-0000-0000-000000000000")
    assert calls == [("00000000-0000-0000-0000-000000000000", 11264)]


@pytest.fixture
def loader(tmp_path, monkeypatch):
    loads, mmap_modes = [], []

    @contextmanager
    def mmap_option(mode):
        mmap_modes.append(mode)
        yield

    def load(*args, **kwargs):
        loads.append((args, kwargs))
        return {"weight": 17}

    @contextmanager
    def empty():
        yield

    torch = SimpleNamespace(
        load=load,
        serialization=SimpleNamespace(set_default_mmap_options=mmap_option),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "accelerate", SimpleNamespace(init_empty_weights=empty))
    inference = SimpleNamespace(WanTransformer=Model, AutoencoderKLWan=Model, CLIPModel=Model)
    return tmp_path, inference, torch, loads, mmap_modes


def test_fixed_cpu_tensor_load_uses_private_mmap_and_weights_only(loader):
    import mmap

    root, inference, torch, loads, modes = loader
    path = root / "Wan2.1_VAE.pth"
    path.touch()
    with mapped_loading(inference, root):
        assert torch.load(path, map_location="cpu") == {"weight": 17}
    assert loads == [((path,), {"map_location": "cpu", "mmap": True, "weights_only": True})]
    assert modes == [mmap.MAP_PRIVATE]


def test_unrelated_load_is_not_reconfigured(loader):
    root, inference, torch, loads, modes = loader
    with mapped_loading(inference, root):
        torch.load("unrelated.pth", map_location="cuda", weights_only=False)
    assert loads == [(("unrelated.pth",), {"map_location": "cuda", "weights_only": False})]
    assert modes == []


def test_model_alias_cannot_escape_the_fixed_root(loader, tmp_path):
    root, inference, torch, loads, _ = loader
    outside = tmp_path.parent / (tmp_path.name + "-outside.pth")
    outside.touch()
    (root / "Wan2.1_VAE.pth").symlink_to(outside)
    with mapped_loading(inference, root), pytest.raises(ValueError, match="outside"):
        torch.load(root / "Wan2.1_VAE.pth", map_location="cpu")
    assert not loads


def test_mapped_load_cannot_select_gpu_or_extra_positional_arguments(loader):
    root, inference, torch, loads, _ = loader
    path = root / "Wan2.1_VAE.pth"
    path.touch()
    with mapped_loading(inference, root):
        with pytest.raises(ValueError, match="CPU"):
            torch.load(path, map_location="cuda")
        with pytest.raises(ValueError, match="CPU"):
            torch.load(path, "cpu")
    assert not loads


def test_all_process_local_overrides_restore_after_failure(loader):
    root, inference, torch, _, _ = loader
    original_load = torch.load
    with pytest.raises(RuntimeError, match="Inference failed"):
        with mapped_loading(inference, root):
            assert inference.WanTransformer is not Model and torch.load is not original_load
            raise RuntimeError("Inference failed")
    assert torch.load is original_load
    assert all(value is Model for value in vars(inference).values())


def test_wrong_vae_or_clip_filename_is_rejected_before_any_tensor_load(loader):
    root, inference, _, loads, _ = loader
    with mapped_loading(inference, root):
        for cls in [inference.AutoencoderKLWan, inference.CLIPModel]:
            with pytest.raises(ValueError, match="configured"):
                cls.from_pretrained(root / "unrelated.pth")
    assert not loads


def test_clip_constructor_uses_meta_and_restores_its_factory_on_failure(loader, monkeypatch):
    root, inference, _, loads, _ = loader
    path = root / "models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth"
    path.touch()
    module = ModuleType("station_test_clip")
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("Constructor failed")

    module._clip = factory

    class Clip(Model):
        def __init__(self):
            module._clip(device="cpu", return_transforms=True)

    Clip.__module__ = module.__name__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    inference.CLIPModel = Clip
    with mapped_loading(inference, root):
        with pytest.raises(RuntimeError, match="Constructor failed"):
            inference.CLIPModel.from_pretrained(path)
        assert module._clip is factory
    assert calls == [{"device": "meta", "return_transforms": True}]
    assert not loads
