"""Offline CPU-only SDK/feature/codec probe; no portrait or model inference."""

import importlib.metadata
import json
import os
import socket
import subprocess
import sys
from pathlib import Path


def denied(*args, **kwargs):
    raise RuntimeError("Avatar preparation cannot access the network")


def main():
    folder = Path(sys.argv[1])
    if sys.version_info[:3] != (3, 10, 21) or Path(sys.base_prefix).resolve() != folder / "python":
        raise RuntimeError("Avatars require their own prepared Python")
    socket.socket.connect = socket.socket.sendto = socket.getaddrinfo = denied
    os.environ.update(USE_TF="0", USE_FLAX="0")
    sys.path.insert(0, str(folder / "source"))
    import av
    import cv2
    import imageio_ffmpeg
    import torch
    from sonic import test
    from src.dataset.face_align.align import AlignImage
    from src.models.audio_adapter.audio_proj import AudioProjModel
    from src.pipelines.pipeline_sonic import SonicPipeline
    from transformers import AutoFeatureExtractor

    if torch.cuda.device_count() != 0:
        raise RuntimeError("Avatar environment inspection must not use a GPU")
    expected = {
        "torch": "2.14.0",
        "torchvision": "0.29.0",
        "transformers": "4.43.2",
        "diffusers": "0.29.0",
        "accelerate": "0.33.0",
        "opencv-python-headless": "4.11.0.86",
    }
    if any(importlib.metadata.version(k) != v for k, v in expected.items()):
        raise RuntimeError("The avatar dependencies differ from the fixed recipe")
    if (
        not all(callable(v) for v in (test, AlignImage, AudioProjModel, SonicPipeline, av.open))
        or cv2.__version__ != "4.11.0"
    ):
        raise RuntimeError("The SDK lacks the fixed headless avatar integration")
    extractor = AutoFeatureExtractor.from_pretrained(folder / "models/whisper-tiny", local_files_only=True)
    if extractor.sampling_rate != 16000:
        raise RuntimeError("The offline audio feature extractor changed")
    binaries = list((Path(imageio_ffmpeg.__file__).parent / "binaries").glob("ffmpeg-linux*"))
    if (
        len(binaries) != 1
        or binaries[0].resolve() != binaries[0]
        or not binaries[0].is_relative_to(folder / "venv")
        or not os.access(binaries[0], os.X_OK)
    ):
        raise RuntimeError("Avatar finishing requires its prepared offline FFmpeg")
    subprocess.run([str(binaries[0]), "-version"], check=True, capture_output=True, timeout=10)
    (folder / "bin/ffmpeg").symlink_to(os.path.relpath(binaries[0], folder / "bin"))
    (folder / "probe.json").write_text(
        json.dumps(
            dict(offline_sdk=True, audio_features=True, ffmpeg=True, gpu_used=False, inference_tested=False)
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
