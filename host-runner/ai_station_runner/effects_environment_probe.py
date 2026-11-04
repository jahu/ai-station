"""Offline CPU-only fixed SDK/codec/schema probe; never loads model weights."""

import importlib.metadata
import json
import socket
import sys
from pathlib import Path


def denied(*args, **kwargs):
    raise RuntimeError("Effects preparation cannot access the network")


def main():
    folder = Path(sys.argv[1])
    if sys.version_info[:3] != (3, 12, 14) or Path(sys.base_prefix).resolve() != folder / "python":
        raise RuntimeError("Effects require their own prepared Python")
    socket.socket.connect = socket.socket.sendto = socket.getaddrinfo = denied
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(folder / "source"))
    import av
    import numpy
    import pydantic
    import torch
    from mmaudio.eval_utils import generate
    from mmaudio.ext.bigvgan_v2.bigvgan import BigVGAN
    from mmaudio.model.networks import get_my_mmaudio
    from mmaudio.model.utils.features_utils import FeaturesUtils

    from ai_station_runner.effects_job import render
    from ai_station_runner.timeline_job import render as render_timeline

    if torch.cuda.device_count() != 0:
        raise RuntimeError("Effects inspection must not use a GPU")
    expected = {
        "torch": "2.8.0+cu126",
        "torchvision": "0.23.0+cu126",
        "torchaudio": "2.8.0+cu126",
        "open_clip_torch": "2.32.0",
        "timm": "1.0.30",
        "av": "16.1.0",
        "numpy": "2.0.2",
        "pydantic": "2.14.2",
        "setuptools": "78.1.0",
    }
    if any(importlib.metadata.version(k) != v for k, v in expected.items()):
        raise RuntimeError("Effects dependencies differ from the fixed recipe")
    if (
        not all(
            callable(v) for v in (generate, BigVGAN, get_my_mmaudio, FeaturesUtils, render, render_timeline)
        )
        or not av.Codec("libx264", "w").is_encoder
        or not numpy.isfinite(numpy.zeros(4)).all()
        or int(pydantic.VERSION.split(".")[0]) != 2
    ):
        raise RuntimeError("The prepared effects inference/CPU mixing integration is unavailable")
    config = json.loads((folder / "models/clip/open_clip_config.json").read_text())
    if not isinstance(config.get("model_cfg"), dict):
        raise RuntimeError("The fixed offline CLIP config is unavailable")
    (folder / "probe.json").write_text(
        json.dumps(
            dict(offline_sdk=True, cpu_codec=True, schemas=True, gpu_used=False, inference_tested=False)
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
