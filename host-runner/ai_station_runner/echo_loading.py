"""Process-local, experimental loading of the existing complete Echo weights.

No model conversion or upstream patch is written. This adapter is not selected
by native dispatch until bounded loading and actual output are qualified.
"""

import importlib
import inspect
import json
import mmap
import os
from contextlib import contextmanager
from pathlib import Path


def qualification_scope(run_id):
    if os.environ.get("AI_STATION_REAL_GPU_TESTS") != "1":
        raise ValueError("Experimental Echo loading requires explicit real-test opt-in")
    from ai_station_runner.memory_scope import require_scope

    return require_scope(run_id, 11264)


def constructor_options(cls, values):
    parameters = inspect.signature(cls.__init__).parameters
    return {key: value for key, value in values.items() if key in parameters and key != "self"}


def transformer_options(path, additional):
    config = json.loads((Path(path) / "config.json").read_text())
    options = dict(additional)
    for source, target in options.get("dict_mapping", {}).items():
        options[target] = config[source]
    return config, options


def assign_complete(model, state, *, dtype=None):
    """No random/meta fallback: every registered tensor must come from weights."""
    result = model.load_state_dict(state, strict=True, assign=True)
    if any(tensor.is_meta for tensor in (*model.parameters(), *model.buffers())):
        raise ValueError("The Echo checkpoint left uninitialized model tensors")
    if dtype is not None:
        model.to(dtype=dtype)
    return result


@contextmanager
def mapped_loading(inference, model_root):
    import accelerate
    import torch

    root = Path(model_root).resolve(strict=True)
    mapped_files = {
        root / "Wan2.1_VAE.pth",
        root / "models_t5_umt5-xxl-enc-bf16.pth",
        root / "models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
    }
    original_load = torch.load
    original_transformer = inference.WanTransformer
    original_vae = inference.AutoencoderKLWan
    original_clip = inference.CLIPModel

    def load(path, *args, **kwargs):
        # Only the three fixed local tensor files gain mmap; unrelated loads
        # retain their original behavior. No decoder/URL/file-like load changes.
        if isinstance(path, (str, os.PathLike)) and Path(path).absolute() in mapped_files:
            if Path(path).resolve(strict=True) not in mapped_files:
                raise ValueError("The Echo tensor file moved outside its model root")
            if args or kwargs.get("map_location") not in {None, "cpu"}:
                raise ValueError("Memory-mapped Echo weights require a CPU tensor load")
            kwargs = {**kwargs, "map_location": "cpu", "mmap": True, "weights_only": True}
            with torch.serialization.set_default_mmap_options(mmap.MAP_PRIVATE):
                return original_load(path, *args, **kwargs)
        return original_load(path, *args, **kwargs)

    class MappedTransformer(original_transformer):
        @classmethod
        def from_pretrained(
            cls,
            pretrained_model_path,
            subfolder=None,
            transformer_additional_kwargs=None,
            low_cpu_mem_usage=False,
            torch_dtype=None,
        ):
            path = Path(pretrained_model_path)
            if subfolder is not None:
                path /= subfolder
            if path.resolve(strict=True) != root:
                raise ValueError("Use the configured Echo base model")
            config, options = transformer_options(path, transformer_additional_kwargs or {})
            with accelerate.init_empty_weights():
                model = cls.from_config(config, **options)
            model._station_loading_dtype = torch_dtype
            # infer_flash next loads the full audio-aware flash checkpoint. Do
            # not load the incomplete original video transformer first.
            return model

        def load_state_dict(self, state_dict, strict=True, assign=False):
            result = super().load_state_dict(state_dict, strict=True, assign=True)
            if any(t.is_meta for t in (*self.parameters(), *self.buffers())):
                raise ValueError("The flash checkpoint left uninitialized model tensors")
            self.to(dtype=self._station_loading_dtype)
            return result

    def prefix_model(cls, path, additional, filename):
        if Path(path).absolute() != root / filename or Path(path).resolve(strict=True) != root / filename:
            raise ValueError("Use the configured Echo tensor file")
        with accelerate.init_empty_weights():
            model = cls(**constructor_options(cls, additional))
        state = torch.load(path, map_location="cpu")
        assign_complete(model, {"model." + key: value for key, value in state.items()})
        return model

    class MappedVae(original_vae):
        @classmethod
        def from_pretrained(cls, pretrained_model_path, additional_kwargs=None):
            return prefix_model(cls, pretrained_model_path, additional_kwargs or {}, "Wan2.1_VAE.pth")

    class MappedClip(original_clip):
        @classmethod
        def from_pretrained(cls, pretrained_model_path, transformer_additional_kwargs=None):
            if (
                Path(pretrained_model_path).absolute()
                != root / "models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth"
            ):
                raise ValueError("Use the configured Echo tensor file")
            # Upstream _clip explicitly moves its new model to CPU inside the
            # constructor. Select meta for that construction only, preserving
            # the original transforms and complete checkpoint assignment.
            module = importlib.import_module(original_clip.__module__)
            original_factory = module._clip

            def meta_factory(*args, **kwargs):
                return original_factory(*args, **{**kwargs, "device": "meta"})

            module._clip = meta_factory
            try:
                return prefix_model(
                    cls,
                    pretrained_model_path,
                    transformer_additional_kwargs or {},
                    "models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
                )
            finally:
                module._clip = original_factory

    torch.load = load
    inference.WanTransformer = MappedTransformer
    inference.AutoencoderKLWan = MappedVae
    inference.CLIPModel = MappedClip
    try:
        yield
    finally:
        torch.load = original_load
        inference.WanTransformer = original_transformer
        inference.AutoencoderKLWan = original_vae
        inference.CLIPModel = original_clip
