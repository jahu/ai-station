"""Owned GGUF and opaque SDK inspection for native CPU model Runs."""

import platform

from fastapi import HTTPException

from ai_station_runner.config import get_settings
from ai_station_runner.darwin_llama import memory_budget
from ai_station_runner.darwin_llama_environment import Environment
from ai_station_runner.gguf_context import inspect_context
from ai_station_runner.owned_models import verify_owned_model


def verify(body):
    environment = Environment(body.runtime_profile)
    if platform.system() != "Darwin" or platform.machine() != environment.architecture:
        raise HTTPException(503, "The native model profile requires its matching Mac Host Runner")
    root = get_settings().host_data_dir().resolve(strict=True)
    try:
        checked = environment.resolve_id(root, body.environment_id) if body.environment_id else None
        path = verify_owned_model(root, body.host_path, body.model_sha256)
        info = path.stat()
        matches = info.st_size == body.size_bytes and abs(info.st_mtime - body.mtime) <= 0.001
        context = inspect_context(path, body.size_bytes, body.mtime) if matches else None
        budget = memory_budget(body.size_bytes, body.context_size, context) if matches else None
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Native model or SDK metadata requires inspection") from exc
    return {
        "host_path": None,
        "relative_path": body.host_path,
        "sha256": body.model_sha256,
        "checksum_source": "verified_download",
        "present": True,
        "regular_file": True,
        "symlink": False,
        "size_bytes": info.st_size,
        "mtime": info.st_mtime,
        "matches_observation": matches,
        "context_profile": context,
        "image": None,
        "native": {
            "present": checked is not None,
            "runtime_profile": body.runtime_profile,
            "environment_id": body.environment_id,
            "manifest_sha256": checked["observation"]["manifest_sha256"] if checked else None,
            "architecture": environment.architecture,
            "compute_target": "cpu",
            "memory_enforcement": "admission_only",
            "zero_swap_guaranteed": False,
        },
        "cpu": {
            "runtime_profile": body.runtime_profile,
            "ram_mib": budget,
            "context_size": body.context_size,
        },
        "error": "" if matches else "The owned model file changed since its observation",
    }
