"""Pinned, app-owned CPU embedding files. Importing this module never downloads."""

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

from app.paths import PathBoundaryError, safe_join

MODEL_ID = "multilingual-e5-small-int8-v1"
REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
REPOSITORY = "Xenova/multilingual-e5-small"
FILES = {
    "model_quantized.onnx": {
        "remote": "onnx/model_quantized.onnx",
        "size": 118308185,
        "sha256": "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
    },
    "tokenizer.json": {
        "remote": "tokenizer.json",
        "size": 17082730,
        "sha256": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    },
}
RELATIVE = f"cache/embeddings/{MODEL_ID}"
DIMENSION = 384
CPU_THREADS = 2
MAX_CHARACTERS = 16000


def descriptor():
    return {
        "id": MODEL_ID,
        "name": "Multilingual E5 Small",
        "format": "ONNX · INT8",
        "license": "MIT",
        "size_bytes": sum(f["size"] for f in FILES.values()),
        "dimension": DIMENSION,
        "execution_target": "container",
        "device": "CPU",
        "cpu_threads": CPU_THREADS,
        "repository": REPOSITORY,
        "revision": REVISION,
        "source_url": f"https://huggingface.co/{REPOSITORY}/tree/{REVISION}",
        "files": [
            {
                "filename": name,
                "size_bytes": item["size"],
                "sha256": item["sha256"],
                "url": f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{item['remote']}",
            }
            for name, item in FILES.items()
        ],
        "original_model_url": "https://huggingface.co/intfloat/multilingual-e5-small",
    }


def directory(root: Path, *, create=False):
    path = root.resolve()
    for part in RELATIVE.split("/"):
        path = path / part
        if path.is_symlink():
            raise PathBoundaryError("Embedding model folders cannot be symlinks")
        if create:
            path.mkdir(exist_ok=True, mode=0o700)
    if path != safe_join(root, RELATIVE):
        raise PathBoundaryError("Embedding files left application storage")
    return path


def model_file(root, name):
    if name not in FILES and name != "installed.json":
        raise ValueError("Unknown embedding model file")
    path = directory(root) / name
    if path.is_symlink():
        raise PathBoundaryError("Embedding model files cannot be symlinks")
    return path


def file_signature(path):
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino, "device": stat.st_dev}


def verify_file(root, name):
    path = model_file(root, name)
    spec = FILES[name]
    before = file_signature(path)
    if before["size"] != spec["size"]:
        raise ValueError("Embedding file has the wrong size; prepare the local model again")
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != spec["sha256"] or file_signature(path) != before:
        raise ValueError("Embedding file verification failed; prepare the local model again")
    return before


def write_receipt(root):
    signatures = {name: verify_file(root, name) for name in FILES}
    value = {"model_id": MODEL_ID, "revision": REVISION, "files": signatures}
    path = model_file(root, "installed.json")
    temporary = directory(root) / ("receipt-" + os.urandom(8).hex() + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return value


def installation(root):
    try:
        path = model_file(root, "installed.json")
        if path.stat().st_size > 8192:
            raise ValueError("Invalid embedding installation receipt")
        value = json.loads(path.read_text())
        expected = {
            "model_id": MODEL_ID,
            "revision": REVISION,
            "files": {name: file_signature(model_file(root, name)) for name in FILES},
        }
        if value != expected:
            raise ValueError("Embedding files changed; prepare the local model again")
        return {"installed": True, "reason": None, "receipt": value}
    except (OSError, ValueError, TypeError):
        return {
            "installed": False,
            "reason": "Local embedding files are missing or changed.",
            "receipt": None,
        }


def dependencies_available():
    return all(importlib.util.find_spec(name) is not None for name in ["onnxruntime", "tokenizers", "numpy"])


def storage(root):
    present = 0
    for name, item in FILES.items():
        try:
            path = model_file(root, name)
            if path.is_file() and path.stat().st_size == item["size"]:
                present += item["size"]
        except (OSError, ValueError):
            pass
    # Size-matched cache entries are hints, not verified files. A corrupt
    # existing object must coexist with its replacement until hash verification.
    replacement = 0 if installation(root)["installed"] else max(item["size"] for item in FILES.values())
    return {
        "free_bytes": shutil.disk_usage(root).free,
        "required_bytes": sum(item["size"] for item in FILES.values()) - present + replacement + 64 * 1024**2,
        "cached_bytes_estimate": present,
    }
