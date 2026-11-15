"""Closed session request: one fixed runtime, owned references and reserved GPUs."""

import os
import stat
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.live_environment import PROFILE
from ai_station_runner.media_inputs import MediaInput
from ai_station_runner.security import resolve_child

NAME = "live_identity"
RAM_MIB = 12288
PERMISSIONS = {"filesystem_read", "workspace_write"}


class Runtime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["live-identity-linux-x86-64-python312-v1"] = PROFILE
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class Reference(MediaInput):
    size_bytes: StrictInt = Field(ge=1, le=20 * 1024**2)


class LiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: UUID
    managed_runtime: Runtime
    image: Reference | None = None
    voice: Reference | None = None
    gpus: list[StrictInt] = Field(min_length=1, max_length=2)
    ram_mib: Literal[12288] = RAM_MIB
    seed: StrictInt = Field(ge=0, le=2147483647)
    deadline_at: float = Field(gt=0, strict=True, allow_inf_nan=False)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def media(self):
        if (
            self.image is None
            and self.voice is None
            or len(self.gpus) != int(self.image is not None) + int(self.voice is not None)
            or len(set(self.gpus)) != len(self.gpus)
            or any(v < 0 for v in self.gpus)
            or set(self.permissions) != PERMISSIONS
        ):
            raise ValueError("Reserve one distinct GPU per enabled live medium and its explicit permissions")
        return self


def reference_snapshot(root, descriptor):
    """Open a direct artifact once, then bind every child to those exact bytes."""
    from ai_station_runner.live_ipc import memory_snapshot

    relative = descriptor.relative_path
    if not relative.startswith(("artifacts/", "uploads/")):
        raise ValueError("Live references must be owned application artifacts")
    root = Path(root).resolve(strict=True)
    path = resolve_child(root, relative)
    if path != root / relative:
        raise ValueError("Live reference cannot cross symlinks")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_size != descriptor.size_bytes
        ):
            raise ValueError("The live reference is not a direct owned file with its frozen size")
        data = source.read(20 * 1024**2 + 1)
    import hashlib
    import hmac

    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), descriptor.sha256):
        raise ValueError("The frozen live reference changed")
    return memory_snapshot(data)
