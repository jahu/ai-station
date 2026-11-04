"""CPU-only checks inside each newly prepared, separately pinned environment."""

import importlib.metadata as metadata
import json
import os
import sys
from pathlib import Path


def main(folder, group):
    folder = Path(folder)
    if group not in {"fish", "transcription"} or sys.version_info[:3] != (3, 12, 14):
        raise ValueError("Use the fixed Fish/Whisper interpreter and environment")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        raise ValueError("Environment checks must not use GPUs")

    def offline(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise PermissionError("Prepared voice probes stay offline")

    sys.addaudithook(offline)
    if group == "fish":
        source = folder / "source"
        sys.path.insert(0, str(source))
        from fish_speech.models.dac.inference import load_model
        from fish_speech.models.text2semantic.llama import DualARTransformer

        if not callable(load_model) or not callable(DualARTransformer.from_pretrained):
            raise ValueError("Fish semantic/codec imports are unavailable")
        for name, module in tuple(sys.modules.items()):
            if name.startswith("fish_speech.") and getattr(module, "__file__", None):
                if not Path(module.__file__).resolve().is_relative_to(source / "fish_speech"):
                    raise ValueError("Fish imported another installation")
        for name, version in {
            "torch": "2.8.0+cu126",
            "torchaudio": "2.8.0+cu126",
            "transformers": "5.19.0",
            "protobuf": "3.19.6",
        }.items():
            if metadata.version(name) != version:
                raise ValueError("Fish dependency differs from the qualified selection")
    else:
        import av
        from faster_whisper import WhisperModel

        if metadata.version("protobuf") == "3.19.6":
            raise ValueError("Whisper must not inherit Fish's protobuf environment")
        av.AudioResampler(format="flt", layout="mono", rate=16000)
        model = WhisperModel(
            str(folder / "models/transcription"),
            device="cpu",
            compute_type="int8",
            cpu_threads=2,
            num_workers=1,
            local_files_only=True,
        )
        if not model:
            raise ValueError("The offline Whisper model did not load")
    print(json.dumps({"environment": group, "cpu_probe": "passed", "inference_tested": False}), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
