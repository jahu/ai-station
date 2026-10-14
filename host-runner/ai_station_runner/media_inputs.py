"""Typed identity of app-owned media; no paths outside the data root."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class MediaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(ge=1, le=2 * 1024**3)
