"""Offline import/graph check. This is not a GPU or live-session acceptance test."""

import json
import sys
from pathlib import Path


def main():
    folder = Path(sys.argv[1]).resolve(strict=True)
    import cv2
    import librosa
    import numpy
    import onnx
    import onnxruntime
    import soundfile
    import torch
    import torchaudio
    import transformers

    assert sys.version_info[:3] == (3, 12, 14)
    assert torch.__version__.split("+")[0] == "2.14.0"
    assert onnxruntime.__version__ == "1.32.0"
    assert transformers.__version__ == "4.46.3"
    assert numpy.__version__ == "1.26.4"
    assert "CUDAExecutionProvider" in onnxruntime.get_available_providers()
    assert torchaudio.compliance.kaldi.fbank(torch.zeros(1, 16000), sample_frequency=16000).isfinite().all()
    assert cv2.__version__.startswith("4.11.")
    assert librosa.__version__ == "0.10.2.post1"
    assert soundfile.__version__
    assert onnx.load(folder / "models/inswapper_128_fp16.onnx", load_external_data=False).graph.name
    print(json.dumps({"live_environment_imports_checked": True, "gpu_inference_tested": False}), flush=True)


if __name__ == "__main__":
    main()
