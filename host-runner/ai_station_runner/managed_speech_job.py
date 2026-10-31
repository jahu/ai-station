"""Repository-owned offline Chatterbox v3 CLI for prepared speech environments.

The native adapter selects this fixed helper only for an activated managed
environment. Existing explicitly configured external adapters keep priority.
"""

import argparse
import json
import os
import socket
import tempfile
from pathlib import Path
from uuid import UUID


def deny_network(*args, **kwargs):
    raise RuntimeError("Managed speech inference cannot access the network")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=UUID, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--ref", type=Path, required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cfg", type=float, default=0.4)
    parser.add_argument("--exaggeration", type=float, default=0.8)
    parser.add_argument("--temperature", type=float, default=0.6)
    args = parser.parse_args()
    if (
        not 1 <= len(args.text.strip()) <= 1000
        or not 0 <= args.cfg <= 1
        or not 0 <= args.exaggeration <= 1.5
        or not 0.05 <= args.temperature <= 1.2
    ):
        parser.error("Use bounded text and supported speech delivery settings")
    if args.out.exists() or args.out.is_symlink():
        parser.error("Speech output already exists")
    folder = args.environment.resolve(strict=True)
    receipt = json.loads((folder / "ready.json").read_text())
    if (
        not receipt.get("environment_prepared")
        or receipt.get("profile") != "chatterbox-v3-linux-x86-64-python312-v1"
    ):
        parser.error("The speech environment has not completed preparation")
    from ai_station_runner.memory_scope import require_scope
    from ai_station_runner.speech_chunks import text_chunks

    require_scope(str(args.run_id), 11264)
    os.environ.update(
        {
            "HF_HOME": str(folder / "cache"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PKUSEG_HOME": str(folder / "segmenter"),
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    import numpy as np
    import soundfile
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    if not torch.cuda.is_available():
        raise RuntimeError("This speech profile requires an available CUDA GPU")
    torch.cuda.reset_peak_memory_stats()
    model = ChatterboxMultilingualTTS.from_local(folder / "models", device="cuda", t3_model="v3")
    parts = []
    chunks = text_chunks(args.text)
    for index, text in enumerate(chunks):
        print(f"speech.chunk.started {index + 1}/{len(chunks)}", flush=True)
        audio = (
            model.generate(
                text,
                language_id="pl",
                audio_prompt_path=str(args.ref),
                cfg_weight=args.cfg,
                exaggeration=args.exaggeration,
                temperature=args.temperature,
                repetition_penalty=2.0,
                min_p=0.05,
                top_p=1.0,
            )
            .detach()
            .cpu()
            .numpy()
            .squeeze()
        )
        if audio.ndim != 1 or not 0.1 <= len(audio) / model.sr < 30 or not np.isfinite(audio).all():
            raise RuntimeError("Speech returned an invalid or token-limit-length part")
        parts.append(audio)
        print(f"speech.chunk.completed {index + 1}/{len(chunks)}", flush=True)
    complete = np.concatenate(parts)
    if len(complete) / model.sr > 300 or len(complete) * 2 > 20 * 1024**2:
        raise RuntimeError("Complete speech exceeded its output budget")
    with tempfile.NamedTemporaryFile(dir=args.out.parent, prefix=".speech-", suffix=".wav") as temporary:
        soundfile.write(temporary.name, complete, model.sr, subtype="PCM_16")
        # Publish only the complete result, without replacing a concurrent output.
        os.link(temporary.name, args.out)
    print(
        json.dumps(
            {
                "speech_complete": True,
                "sample_rate": model.sr,
                "chunks": len(chunks),
                "peak_allocated_gpu_bytes": torch.cuda.max_memory_allocated(),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
