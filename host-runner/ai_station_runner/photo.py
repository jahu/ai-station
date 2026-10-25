"""argv builders for the existing photo_pipe.py. The script itself is not modified."""

from __future__ import annotations

import json
import re
from pathlib import Path

_DEVICE = re.compile(r"^cuda:\d+$")


class PhotoCommandError(ValueError):
    pass


def device_for(gpu: str) -> str:
    if not str(gpu).isdigit():
        raise PhotoCommandError("GPU must be a discovered numeric index")
    return f"cuda:{int(gpu)}"


def build_photo_argv(
    python: str,
    script: str,
    *,
    mode: str,
    backend: str | None,
    prompt: str,
    negative: str | None,
    edit_prompt: str,
    width: int | None,
    height: int | None,
    steps: int | None,
    cfg: float | None,
    seed: int | None,
    max_side: int | None,
    repeats: int | None,
    device: str,
    output: str,
    inputs: list[str],
    prompt_style: str = "pipeline",
    model_snapshot: dict | None = None,
) -> list[str]:
    if model_snapshot is not None and (backend != "qwen" or mode == "upscale"):
        raise PhotoCommandError("Selected checkpoints require a compatible Qwen image operation")
    if prompt_style not in {"pipeline", "prompt", "instruction"}:
        raise PhotoCommandError("Unknown photo prompt profile")
    if prompt_style == "prompt" and mode != "t2i":
        raise PhotoCommandError("Prompt-only styling supports text-to-image only")
    if prompt_style == "instruction" and mode not in {"img2img", "recompose"}:
        raise PhotoCommandError("Instruction-only styling supports Edit and Recompose only")
    if not _DEVICE.match(device):
        raise PhotoCommandError("Device must look like cuda:<index>")
    for value in (python, script, output, *inputs):
        if not value or value.startswith("-"):
            raise PhotoCommandError("Refusing an empty or flag-like path")
    argv = [python, script]
    if mode == "t2i":
        if backend not in {"qwen", "juggernaut"}:
            raise PhotoCommandError("Text-to-image backend must be qwen or juggernaut")
        if not prompt.strip():
            raise PhotoCommandError("Prompt is required")
        argv += [
            "t2i",
            "--backend",
            backend,
            "--prompt",
            prompt,
            "--width",
            str(width or 832),
            "--height",
            str(height or 1216),
            "--steps",
            str(steps or 35),
            "--cfg",
            str(cfg if cfg is not None else 5.0),
            "--seed",
            str(seed if seed is not None else 42),
            "--device",
            device,
            "--out",
            output,
        ]
        if negative:
            argv += ["--negative", negative]
        return _wrap(argv, prompt_style, model_snapshot)
    if mode == "img2img":
        if len(inputs) != 1:
            raise PhotoCommandError("Edit requires exactly one input image")
        if not edit_prompt.strip():
            raise PhotoCommandError("Edit instruction is required")
        edit = argv + [
            "img2img",
            "--input",
            inputs[0],
            "--edit-prompt",
            edit_prompt,
            "--max-side",
            str(max_side or 1216),
            "--qwen-steps",
            str(steps or 30),
            "--device",
            device,
            "--out",
            output,
        ]
        return _wrap(edit, prompt_style, model_snapshot)
    if mode == "recompose":
        if not inputs:
            raise PhotoCommandError("Recompose requires at least one reference")
        if not prompt.strip():
            raise PhotoCommandError("Scene prompt is required")
        argv += [
            "recompose",
            "--prompt",
            prompt,
            "--width",
            str(width or 832),
            "--height",
            str(height or 1216),
            "--steps",
            str(steps or 30),
            "--cfg",
            str(cfg if cfg is not None else 6.0),
            "--device",
            device,
            "--out",
            output,
        ]
        for ref in inputs:
            argv += ["--reference", ref]
        return _wrap(argv, prompt_style, model_snapshot)
    if mode == "upscale":
        if len(inputs) != 1:
            raise PhotoCommandError("Upscale requires exactly one input image")
        return argv + [
            "upscale",
            "--input",
            inputs[0],
            "--device",
            device,
            "--repeats",
            str(repeats or 1),
            "--out",
            output,
        ]
    raise PhotoCommandError(f"Unknown photo mode: {mode}")


def _profile(argv):
    return [argv[0], str(Path(__file__).with_name("photo_job.py")), *argv[1:]]


def _wrap(argv, style, model):
    if model is None:
        return _profile(argv) if style != "pipeline" else argv
    return [
        argv[0],
        str(Path(__file__).with_name("photo_job.py")),
        "--station-model-json",
        json.dumps(model, separators=(",", ":")),
        "--station-profile",
        style,
        *argv[1:],
    ]


def expected_upscale_size(width: int, height: int, repeats: int = 1) -> tuple[int, int]:
    factor = 4 ** max(repeats, 1)
    return width * factor, height * factor


def path_is_file(path: str) -> bool:
    return Path(path).is_file()
