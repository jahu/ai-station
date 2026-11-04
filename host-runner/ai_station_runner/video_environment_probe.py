"""Offline CPU-only headless Wan imports/tokenizer probe; no model inference."""

import importlib.metadata
import json
import socket
import sys
from pathlib import Path


def denied(*args, **kwargs):
    raise RuntimeError("Video preparation cannot access the network")


def main():
    folder, root = Path(sys.argv[1]), Path(sys.argv[2])
    if Path(sys.base_prefix).resolve() != folder / "python":
        raise RuntimeError("Video Python must remain inside its own environment")
    socket.socket.connect = denied
    socket.socket.sendto = denied
    socket.getaddrinfo = denied
    sys.path.insert(0, str(folder / "source"))
    sys.argv = [
        "ai-station-video-setup",
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
    from comfy.text_encoders.spiece_tokenizer import SPieceTokenizer
    from comfy_extras.nodes_model_advanced import ModelSamplingSD3
    from comfy_extras.nodes_wan import Wan22ImageToVideoLatent
    from safetensors import safe_open

    if torch.cuda.device_count() != 0:
        raise RuntimeError("Video environment inspection must not access a GPU")
    for name, version in {"torch": "2.11.0", "torchvision": "0.26.0", "torchaudio": "2.11.0"}.items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError("Video dependencies differ from the coherent fixed recipe")
    if not all(
        callable(value)
        for value in (
            nodes.CLIPLoader,
            nodes.CLIPTextEncode,
            nodes.VAELoader,
            nodes.UNETLoader,
            nodes.KSampler,
            nodes.VAEDecode,
            ModelSamplingSD3,
            Wan22ImageToVideoLatent.execute,
            av.open,
        )
    ):
        raise RuntimeError("The SDK lacks the expected fixed headless video integration")
    encoder = folder / "models/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    if encoder.resolve(strict=True).parent != root / "models/store":
        raise RuntimeError("The offline video tokenizer must use the owned immutable store")
    with safe_open(str(encoder), framework="pt", device="cpu") as weights:
        if weights.get_slice("spiece_model").get_shape()[0] > 8 * 1024**2:
            raise RuntimeError("The bundled video tokenizer exceeded its bound")
        tokenizer = SPieceTokenizer(weights.get_tensor("spiece_model"))
        if not tokenizer("A quiet river at sunrise")["input_ids"]:
            raise RuntimeError("The offline video tokenizer is unavailable")
    (folder / "probe.json").write_text(
        json.dumps(dict(offline_sdk=True, tokenizer=True, gpu_used=False, inference_tested=False)) + "\n"
    )


if __name__ == "__main__":
    main()
