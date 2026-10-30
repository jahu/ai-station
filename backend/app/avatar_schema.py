"""Pure whole-speech avatar settings shared by reviewed callers."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_serializer, model_validator

from app.media_translation_text import TranslationOptions

STANDARD_RAM_MIB = 24576


class AvatarMemorySettings(BaseModel):
    memory_profile: Literal["default", "bounded_11g"] = "default"
    translation: TranslationOptions | None = None

    @model_serializer(mode="wrap")
    def legacy_identity(self, handler):
        values = handler(self)
        if self.translation is None:
            values.pop("translation", None)
        if self.memory_profile == "default":
            values.pop("memory_profile", None)
        if getattr(self, "generation_profile", None) is None:
            values.pop("generation_profile", None)
        else:
            # The fixed whole-recording engine has its own frozen 25-step
            # resolution profile. Do not persist misleading Echo defaults.
            values.pop("size", None)
            values.pop("steps", None)
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
    generation_profile: Literal["sonic_whole_768_v1"] | None = None

    @model_validator(mode="after")
    def whole_profile_controls(self):
        if self.generation_profile is not None and self.translation is not None:
            raise ValueError("The fixed whole-recording recipe has no descriptive prompt to prepare")
        if self.generation_profile is not None and (
            self.memory_profile != "default" or {"size", "steps"} & self.model_fields_set
        ):
            raise ValueError(
                "The whole-recording quality profile owns resolution and steps; omit Echo controls"
            )
        return self
