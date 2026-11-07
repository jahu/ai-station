"""Offline multilingual CLI for an explicitly configured Chatterbox v3 cache.

This app-owned adapter leaves an existing independent clone_pl.py untouched.
Its Python environment and complete cache are operator configuration, never
model-supplied programs or downloaded inference dependencies.
"""

import argparse
import os
import socket
import tempfile
from pathlib import Path


def deny_network(*_args, **_kwargs):
    raise RuntimeError("Configured speech inference cannot access the network")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", type=Path, required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--language", choices=["pl", "en"], default="pl")
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
        parser.error("Inspect the existing speech output")
    cache = os.environ.get("HF_HOME")
    if not cache or not Path(cache).is_dir():
        parser.error("An existing complete Chatterbox cache is required")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    import torch
    import torchaudio
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    if not torch.cuda.is_available():
        raise RuntimeError("Configured speech requires its allocated CUDA GPU")
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
    audio = (
        model.generate(
            args.text,
            language_id=args.language,
            audio_prompt_path=str(args.ref),
            exaggeration=args.exaggeration,
            cfg_weight=args.cfg,
            temperature=args.temperature,
            repetition_penalty=1.2,
            min_p=0.05,
            top_p=1.0,
        )
        .detach()
        .cpu()
    )
    if audio.ndim == 1:
        audio = audio.unsqueeze(0)
    if audio.ndim != 2 or audio.shape[0] != 1 or not torch.isfinite(audio).all():
        raise RuntimeError("Speech returned invalid mono PCM samples")
    if not 0.1 <= audio.shape[-1] / model.sr < 30:
        raise RuntimeError("Speech returned an empty or token-limit-length clip")
    with tempfile.NamedTemporaryFile(dir=args.out.parent, suffix=".wav") as temporary:
        torchaudio.save(temporary.name, audio, model.sr)
        os.link(temporary.name, args.out)


if __name__ == "__main__":
    main()
