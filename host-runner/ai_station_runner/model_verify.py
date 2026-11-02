"""Metadata-only check of an already-present model file. Never downloads or pulls."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from ai_station_runner.config import _split, get_settings
from ai_station_runner.gguf_context import inspect_context
from ai_station_runner.security import PathBoundaryError, ensure_within

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class VerifyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    host_path: str = Field(min_length=1, max_length=1200)
    app_owned: StrictBool = False
    model_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    mtime: float = Field(allow_inf_nan=False)
    check_image: StrictBool = False
    check_context: StrictBool = False
    runtime_profile: (
        Literal[
            "llamacpp-cpu-linux-amd64-v1",
            "llamacpp-native-darwin-arm64-b12032-v2",
            "llamacpp-native-darwin-x86_64-b12032-v2",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda v: v is None)
    environment_id: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$", exclude_if=lambda v: v is None
    )
    context_size: StrictInt | None = Field(
        default=None, ge=512, le=262144, multiple_of=256, exclude_if=lambda v: v is None
    )
    permissions: list[Literal["filesystem_read", "manage_models"]] = Field(max_length=2)

    @model_validator(mode="after")
    def coordinate(self):
        from ai_station_runner.owned_models import validate_reference

        validate_reference(self.host_path, self.model_sha256, self.app_owned)
        if self.runtime_profile and self.runtime_profile.startswith("llamacpp-native-darwin-"):
            if (
                not self.app_owned
                or not self.check_context
                or self.check_image
                or not self.environment_id
                or self.context_size is None
            ):
                raise ValueError(
                    "Native model inspection requires owned weights, context and its opaque SDK reference"
                )
        elif self.environment_id is not None or self.context_size is not None:
            raise ValueError("Native SDK coordinates require an explicit native model profile")
        return self


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
    if body.environment_id is not None:
        from ai_station_runner.native_model_verify import verify

        return verify(body)
    if sys.platform != "linux":
        raise HTTPException(503, "This model inspection profile requires a Linux Host Runner")
    settings = get_settings()
    if body.app_owned:
        from ai_station_runner.owned_models import owned_model

        path = owned_model(body.host_path, body.model_sha256)
    else:
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
    if body.app_owned:
        result.update(
            host_path=None,
            relative_path=body.host_path,
            sha256=body.model_sha256,
            checksum_source="verified_download",
        )
    if body.check_context and matches:
        try:
            result["context_profile"] = inspect_context(path, stat.st_size, stat.st_mtime)
        except (OSError, ValueError):
            result["context_profile"] = None
            result["context_notice"] = "Header estimate unavailable; use conservative fallback"
            if body.app_owned:
                result["error"] = "The app-owned GGUF header could not be verified"
    if not body.check_image:
        return result
    from ai_station_runner.runtime_setup import image_observation

    if body.runtime_profile:
        from ai_station_runner import cpu_runtime_profile as cpu

        if not matches or not body.check_context or not body.app_owned:
            raise HTTPException(422, "CPU preparation requires the verified owned GGUF context")
        try:
            budget = cpu.memory_budget_mib(
                body.size_bytes, cpu.DEFAULT_CONTEXT, result.get("context_profile")
            )
            image_name, image_id = image_observation(app_owned=True, runtime_profile=body.runtime_profile)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        result["cpu"] = {
            "runtime_profile": cpu.PROFILE,
            "ram_mib": budget,
            "context_size": cpu.DEFAULT_CONTEXT,
        }
    else:
        image_name, image_id = image_observation(app_owned=body.app_owned)
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
