"""Offline SDK/tokenizer probe; no GPU access or music model inference."""

import importlib.metadata
import json
import socket
import sys
from pathlib import Path


def denied(*args, **kwargs):
    raise RuntimeError("Music preparation probe cannot access the network")


def main():
    folder = Path(sys.argv[1])
    if Path(sys.base_prefix).resolve() != folder / "python":
        raise RuntimeError("Music Python must remain inside its own environment")
    socket.socket.connect = denied
    socket.socket.sendto = denied
    socket.getaddrinfo = denied
    sys.path.insert(0, str(folder / "source"))
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from transformers import AutoTokenizer

    if not all(callable(v) for v in (AceStepHandler, GenerationConfig, GenerationParams, generate_music)):
        raise RuntimeError("The music SDK lacks the expected offline integration")
    for name, version in {
        "torch": "2.10.0+cu128",
        "torchaudio": "2.10.0+cu128",
        "transformers": "4.57.6",
    }.items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError("The music runtime versions differ from its reviewed profile")
    import torch

    if torch.cuda.device_count() != 0:
        raise RuntimeError("Music environment inspection must not access a GPU")
    tokenizer = AutoTokenizer.from_pretrained(
        str(folder / "models/Qwen3-Embedding-0.6B"), local_files_only=True
    )
    if not tokenizer.encode("A quiet piano instrumental"):
        raise RuntimeError("The complete offline music tokenizer is required")
    (folder / "probe.json").write_text(
        json.dumps(dict(offline_sdk=True, tokenizer=True, gpu_used=False, inference_tested=False)) + "\n"
    )


if __name__ == "__main__":
    main()
