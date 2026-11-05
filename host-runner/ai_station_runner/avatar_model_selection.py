"""Read-only selected-avatar inspection; no model loading or process launch."""

import math
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner import avatar_checkpoints, sonic_runtime
from ai_station_runner.config import get_settings
from ai_station_runner.telemetry import collect


class ManagedRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    profile: Literal["sonic-whole-linux-x86-64-python310-v1"]
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    checkpoint: dict
    managed_runtime: ManagedRuntime
    permissions: list[Literal["filesystem_read"]] = Field(max_length=1)

    @model_validator(mode="after")
    def fixed_source(self):
        avatar_checkpoints.checked_source(self.checkpoint)
        expected = avatar_checkpoints.recipe(self.checkpoint["profile"])
        if self.managed_runtime.manifest_sha256 != expected["runtime_manifest_sha256"]:
            raise ValueError("Use the selected avatar checkpoint's complete reviewed engine")
        return self


def capabilities(body):
    if body.permissions != ["filesystem_read"]:
        raise HTTPException(403, "Avatar model inspection requires filesystem read permission")
    if not avatar_checkpoints.INFERENCE_QUALIFIED:
        return {"available": False, "reason": "Selected avatar checkpoint inference is still being qualified"}
    runtime = body.managed_runtime.model_dump(mode="json")
    try:
        root = get_settings().host_data_dir()
        avatar_checkpoints.selected_environment(root, body.checkpoint, runtime["environment_id"])
        ram = (collect(root).get("memory") or {}).get("total_mib")
        if type(ram) not in {int, float} or not math.isfinite(ram) or ram < 24576:
            raise ValueError("This avatar profile requires at least 24 GiB physical RAM")
        report = sonic_runtime.capabilities(runtime["environment_id"])
        if (
            report.get("available")
            and (report.get("recipe") or {}).get("environment_id") != runtime["environment_id"]
        ):
            raise ValueError("The selected avatar engine changed")
        return {**report, "checkpoint": dict(body.checkpoint), "managed_runtime": runtime}
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "available": False,
            "reason": "The selected avatar weights, engine or hardware are unavailable; inspect Models",
        }
