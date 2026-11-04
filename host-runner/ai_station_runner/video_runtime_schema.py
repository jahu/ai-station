"""Fixed shared runtime identity for video generation and CPU composition."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ManagedRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["wan22-5b-linux-x86-64-python312-v1"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_id: str = Field(pattern=r"^[a-f0-9]{64}$")
