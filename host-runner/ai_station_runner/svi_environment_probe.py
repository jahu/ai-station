"""Offline CPU-only SVI dependency/tokenizer probe; no diffusion inference."""

import importlib
import importlib.metadata
import json
import sys
import types
from pathlib import Path


def main():
    folder, root = Path(sys.argv[1]), Path(sys.argv[2])
    if Path(sys.base_prefix).resolve() != folder / "python":
        raise RuntimeError("SVI Python must remain inside its own environment")

    def offline(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise PermissionError("SVI preparation is offline")

    sys.addaudithook(offline)
    sys.path.insert(0, str(folder / "source"))
    sys.argv = [
        "ai-station-svi-setup",
        "--cpu",
        "--disable-all-custom-nodes",
        "--disable-api-nodes",
        "--base-directory",
        str(folder / "home"),
    ]
    import comfy.options

    comfy.options.enable_args_parsing()
    import av
    import nodes
    import torch
    from comfy.latent_formats import Wan21
    from comfy.text_encoders.spiece_tokenizer import SPieceTokenizer
    from comfy_extras.nodes_model_advanced import ModelSamplingSD3
    from safetensors import safe_open

    if torch.cuda.device_count() != 0:
        raise RuntimeError("SVI environment inspection must not access a GPU")
    for name, version in {
        "torch": "2.11.0",
        "torchvision": "0.26.0",
        "torchaudio": "2.11.0",
        "gguf": "0.19.0",
    }.items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError("SVI dependencies differ from the coherent fixed recipe")
    package = types.ModuleType("ai_station_svi_gguf")
    package.__path__ = [str(folder / "gguf-source")]
    sys.modules[package.__name__] = package
    loader = importlib.import_module(package.__name__ + ".nodes")
    if Wan21().latent_channels != 16 or not all(
        callable(value)
        for value in (
            loader.UnetLoaderGGUF.load_unet,
            nodes.CLIPLoader,
            nodes.CLIPTextEncode,
            nodes.KSamplerAdvanced.sample,
            nodes.VAEDecode,
            ModelSamplingSD3.patch,
            av.open,
        )
    ):
        raise RuntimeError("The SDK lacks the fixed SVI/Wan21 integration")
    encoder = folder / "models/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    if encoder.resolve(strict=True).parent != root / "models/store":
        raise RuntimeError("The SVI tokenizer must use the owned immutable store")
    with safe_open(str(encoder), framework="pt", device="cpu") as weights:
        if weights.get_slice("spiece_model").get_shape()[0] > 8 * 1024**2:
            raise RuntimeError("The SVI tokenizer exceeded its bound")
        tokenizer = SPieceTokenizer(weights.get_tensor("spiece_model"))
        if not tokenizer("A quiet river at sunrise")["input_ids"]:
            raise RuntimeError("The offline SVI tokenizer is unavailable")
    (folder / "probe.json").write_text(
        json.dumps(
            {
                "offline_sdk": True,
                "gguf_loader": True,
                "tokenizer": True,
                "gpu_used": False,
                "inference_tested": False,
            }
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
