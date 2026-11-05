"""Finite owned music model/engine coordinates; no paths, packages or commands."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class ManagedRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["ace-step15-turbo-linux-x86-64-python312-v1"]
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class CheckpointSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["ace-step15-turbo-diffusion-v1"]
    relative_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=8 * 1024**3)
    mtime: float = Field(ge=0, allow_inf_nan=False)
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def namespace(self):
        if self.relative_path != "models/store/" + self.sha256:
            raise ValueError("Select a verified music checkpoint from application storage")
        return self


class CheckpointSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    checkpoint: CheckpointSource
    managed_runtime: ManagedRuntime
    permissions: list[Literal["filesystem_read"]] = Field(max_length=1)


class MusicCheckpointJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: UUID
    deadline_at: float = Field(gt=0, allow_inf_nan=False)
    checkpoint: CheckpointSource
    managed_runtime: ManagedRuntime
