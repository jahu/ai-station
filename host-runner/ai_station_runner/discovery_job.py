"""Managed metadata-only model scan; never opens or mutates model contents."""

import json
import os
import stat
import sys
import time
from pathlib import Path
from uuid import UUID

from ai_station_runner.config import get_settings
from ai_station_runner.discovery import _capabilities, _category, _family, _quant
from ai_station_runner.security import resolve_child

MAX_ENTRIES = 100000
MAX_MODELS = 5000
MAX_SECONDS = 60
FORMATS = {"gguf", "safetensors", "ckpt", "pt", "pth", "bin", "onnx"}


def output_path(run_id: str) -> Path:
    if str(UUID(run_id)) != run_id:
        raise ValueError("Canonical Run UUID required")
    root = get_settings().host_data_dir().resolve()
    relative = f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.json"
    path = resolve_child(root, relative)
    if path != root / relative:
        raise ValueError("Model scan output cannot be redirected through symlinks")
    return path


def inventory(roots: list[Path]) -> dict:
    started = time.monotonic()
    visited = 0
    found = {}
    reports = []

    def failed(error):
        raise error

    for raw in roots:
        root = raw.expanduser().resolve()
        if len(str(root)) > 200:
            raise ValueError("Model root path exceeds the registry storage limit")
        if not root.is_dir():
            reports.append({"path": str(root), "status": "unavailable"})
            continue
        reports.append({"path": str(root), "status": "scanned"})
        category = _category(root)
        device = root.stat().st_dev
        # fwalk anchors stat calls to opened directory descriptors and refuses
        # directory symlinks; no model content is read and no files are created.
        for directory, dirs, files, descriptor in os.fwalk(root, follow_symlinks=False, onerror=failed):
            if os.fstat(descriptor).st_dev != device:
                dirs[:] = []
                raise ValueError("Model root contains a different filesystem; configure it separately")
            visited += len(dirs) + len(files) + 1
            if visited > MAX_ENTRIES or time.monotonic() - started > MAX_SECONDS:
                raise ValueError("Model scan exceeded its traversal budget; narrow configured roots")
            dirs[:] = sorted(name for name in dirs if name not in {".git", ".cache", "__pycache__"})
            for name in sorted(files):
                suffix = Path(name).suffix.lower().lstrip(".")
                if suffix not in FORMATS:
                    continue
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    continue
                path = str(Path(directory) / name)
                if len(path) > 1200:
                    raise ValueError("Model file path exceeds the registry storage limit")
                found[path] = {
                    "host_path": path,
                    "filename": name,
                    "size_bytes": info.st_size,
                    "mtime": info.st_mtime,
                    "format": suffix,
                    "family": _family(name),
                    "quantization": _quant(name),
                    "category": category,
                    "capabilities": _capabilities(category, name),
                    "root_label": str(root),
                }
                if len(found) > MAX_MODELS:
                    raise ValueError("Model scan exceeded 5,000 files; narrow configured roots")
    return {"models": list(found.values()), "roots": reports}


def main(run_id: str):
    if os.getpgrp() != os.getpid():
        raise ValueError("Discovery requires an owned process group")
    output = output_path(run_id)
    if output.exists():
        raise ValueError("Run output already exists")
    roots = [Path(raw) for raw in get_settings().model_roots.split(":") if raw.strip()]
    if not roots:
        raise ValueError("No model roots are configured")
    result = inventory(roots)
    result["run_id"] = run_id
    output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with output.open("x") as handle:
        json.dump(result, handle)
        handle.flush()
        os.fsync(handle.fileno())
    print(f"Discovered {len(result['models'])} model files; no contents were read or changed", flush=True)


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
