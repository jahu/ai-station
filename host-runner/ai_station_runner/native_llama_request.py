"""Native model load coordinates for the existing typed llama.cpp API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.owned_models import validate_reference


class NativeModelLoad(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instance_id: UUID
    run_id: UUID
    runtime_profile: Literal[
        "llamacpp-native-darwin-arm64-b12032-v2", "llamacpp-native-darwin-x86_64-b12032-v2"
    ]
    environment_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    app_owned: Literal[True]
    model_path: str = Field(max_length=100)
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=256 * 1024**3)
    mtime: float = Field(gt=0, allow_inf_nan=False)
    gpus: list[int] = Field(max_length=0)
    context_size: StrictInt = Field(default=4096, ge=512, le=262144, multiple_of=256)
    cache_type: Literal["q8_0"]
    ram_mib: StrictInt = Field(ge=256, le=1048576)
    startup_deadline_at: datetime
    permissions: list[Literal["manage_models", "filesystem_read"]] = Field(max_length=2)

    @model_validator(mode="after")
    def coordinates(self):
        validate_reference(self.model_path, self.model_sha256, True)
        if self.startup_deadline_at.tzinfo is None:
            raise ValueError("Use an absolute native startup deadline")
        return self
