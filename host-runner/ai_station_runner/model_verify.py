"""Metadata-only check of an already-present model file. Never downloads or pulls."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ai_station_runner import llama_runtime
from ai_station_runner.config import _split, get_settings
from ai_station_runner.gguf_context import inspect_context
from ai_station_runner.security import PathBoundaryError, ensure_within

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class VerifyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    host_path: str = Field(min_length=1, max_length=1200)
    size_bytes: int = Field(ge=0)
    mtime: float = Field(allow_inf_nan=False)
    check_image: StrictBool = False
    check_context: StrictBool = False
    permissions: list[Literal["filesystem_read", "manage_models"]] = Field(max_length=2)


def _missing(path: Path, *, symlink: bool, error: str) -> dict:
    return {
        "host_path": str(path),
        "present": False,
        "regular_file": False,
        "symlink": symlink,
        "size_bytes": 0,
        "mtime": 0.0,
        "matches_observation": False,
        "image": None,
        "error": error,
    }


def verify_model(body: VerifyModel) -> dict:
    if set(body.permissions) != {"filesystem_read", "manage_models"}:
        raise HTTPException(403, "Model installation requires filesystem read and model management")
    settings = get_settings()
    roots = _split(settings.model_roots)
    if not roots:
        raise HTTPException(409, "No model roots are configured")
    original = Path(body.host_path)
    if os.path.islink(original):
        return _missing(original, symlink=True, error="Model path cannot be a symlink")
    try:
        path = ensure_within(original, roots)
    except (PathBoundaryError, OSError) as exc:
        raise HTTPException(422, "Model is outside configured roots") from exc
    if os.path.islink(path) or path.is_symlink():
        return _missing(path, symlink=True, error="Model path cannot be a symlink")
    if not path.is_file() or path.is_symlink():
        return _missing(path, symlink=False, error="Model file is missing or is not a regular file")
    stat = path.stat()
    matches = stat.st_size == body.size_bytes and abs(stat.st_mtime - body.mtime) <= 0.001
    result = {
        "host_path": str(path),
        "present": True,
        "regular_file": True,
        "symlink": False,
        "size_bytes": stat.st_size,
        "mtime": stat.st_mtime,
        "matches_observation": matches,
        "image": None,
        "error": "" if matches else "Model file changed since discovery; scan it again",
    }
    if body.check_context and matches:
        try:
            result["context_profile"] = inspect_context(path, stat.st_size, stat.st_mtime)
        except (OSError, ValueError):
            result["context_profile"] = None
            result["context_notice"] = "Header estimate unavailable; use conservative fallback"
    if not body.check_image:
        return result
    image_name = settings.llama_image
    image_id = llama_runtime.docker("image", "inspect", image_name, "--format", "{{.Id}}", missing_ok=True)
    present = bool(image_id) and bool(_IMAGE_ID.fullmatch(image_id or ""))
    result["image"] = {
        "checked": True,
        "name": image_name,
        "id": image_id if present else "",
        "present": present,
    }
    if not present and not result["error"]:
        result["error"] = (
            "Configured llama.cpp image is not installed locally; it is never pulled automatically"
        )
    return result
