"""Pure whole-speech avatar settings shared by reviewed callers."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_serializer, model_validator


class AvatarMemorySettings(BaseModel):
    memory_profile: Literal["default", "bounded_11g"] = "default"

    @model_serializer(mode="wrap")
    def legacy_identity(self, handler):
        values = handler(self)
        if self.memory_profile == "default":
            values.pop("memory_profile", None)
        return values

    @model_validator(mode="after")
    def bounded_shape(self):
        if self.memory_profile == "bounded_11g" and (self.size != 384 or self.steps < 8):
            raise ValueError("The reduced-RAM avatar profile requires 384x384 and at least 8 steps")
        return self


class FullAvatarSettings(AvatarMemorySettings):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    speech_text: str | None = Field(default=None, min_length=1, max_length=1000)
    image_artifact_id: UUID
    audio_artifact_id: UUID
    prompt: str = Field(default="A person speaking naturally, static camera.", min_length=1, max_length=2000)
    size: Literal[256, 384, 512] = 384
    steps: StrictInt = Field(default=8, ge=4, le=30)
    seed: StrictInt = Field(default=43, ge=0, le=2147483647)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")
