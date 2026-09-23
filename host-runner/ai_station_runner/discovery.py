"""Read-only model discovery. Files are never moved, renamed, or deleted."""

from __future__ import annotations

import os
import re
from pathlib import Path

_QUANT = re.compile(r"(Q\d[_0-9A-Za-z]*|BF16|F16|F32|FP16|GGUF)", re.IGNORECASE)
_SKIP = {".git", ".cache", "__pycache__"}


def scan(roots: list[Path]) -> list[dict]:
    found = []
    for root in roots:
        if not root.exists():
            continue
        category = _category(root)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if name not in _SKIP]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    if path.is_symlink():
                        continue
                    stat = path.stat()
                except OSError:
                    continue
                suffix = path.suffix.lower().lstrip(".")
                if suffix not in {"gguf", "safetensors", "ckpt", "pt", "pth", "bin", "onnx"}:
                    continue
                found.append(
                    {
                        "host_path": str(path),
                        "filename": path.name,
                        "size_bytes": stat.st_size,
                        "mtime": stat.st_mtime,
                        "format": suffix,
                        "family": _family(path.name),
                        "quantization": _quant(path.name),
                        "category": category,
                        "capabilities": _capabilities(category, path.name),
                        "root_label": str(root),
                    }
                )
    return found


def _category(root: Path) -> str:
    name = root.name.lower()
    if name in {"llm", "image", "video", "audio", "tts"}:
        return "audio" if name == "tts" else name
    return "other"


def _family(filename: str) -> str:
    lowered = filename.lower()
    for family in ("qwen", "llama", "mistral", "juggernaut", "sdxl", "realesrgan", "whisper"):
        if family in lowered:
            return family
    return ""


def _quant(filename: str) -> str:
    match = _QUANT.search(filename)
    return match.group(1) if match else ""


def _capabilities(category: str, filename: str) -> list[str]:
    caps = []
    if category == "llm":
        caps.append("chat")
    if category == "image":
        caps.append("image")
    if "upscale" in filename.lower() or "realesrgan" in filename.lower():
        caps.append("upscale")
    return caps
