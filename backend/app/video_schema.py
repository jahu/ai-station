"""Pure video settings shared by workspaces and reviewed agent scopes."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_serializer, model_validator

from app.media_translation_text import TranslationOptions


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    translation: TranslationOptions | None = None
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=2000)
    image_artifact_id: UUID | None = None
    width: int = Field(default=1280, ge=128, le=1280, multiple_of=32)
    height: int = Field(default=704, ge=128, le=1280, multiple_of=32)
    frames: int = Field(default=49)
    steps: int = Field(default=20, ge=4, le=40)
    cfg: float = Field(default=5, ge=1, le=10, allow_inf_nan=False)
    seed: int = Field(default=43, ge=0, le=2147483647)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")
    memory_profile: Literal["default", "bounded_11g"] = "default"

    @model_serializer(mode="wrap")
    def legacy_identity(self, handler):
        values = handler(self)
        if self.memory_profile == "default":
            values.pop("memory_profile", None)
        if self.translation is None:
            values.pop("translation", None)
        return values

    @model_validator(mode="after")
    def bounds(self):
        if self.memory_profile == "bounded_11g" and (
            (self.width, self.height) != (1280, 704) or self.steps < 20
        ):
            raise ValueError("The reduced-RAM profile requires 1280x704 and at least 20 steps")
        if self.frames not in {17, 33, 49, 65, 81} or self.width * self.height > 1280 * 704:
            raise ValueError("Video frames or dimensions exceed the profile limit")
        return self


class VideoScene(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=1000)
    duration_seconds: StrictInt = Field(ge=1, le=60)


class LongVideoSettings(VideoRequest):
    duration_seconds: StrictInt = Field(default=15, ge=1, le=60)
    composition_mode: Literal["continuous", "shots"] = "continuous"
    scenes: list[VideoScene] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def no_frames(self):
        if "frames" in self.model_fields_set:
            raise ValueError("Choose duration or short-clip frames, not both")
        if self.scenes is not None:
            if self.composition_mode != "shots":
                raise ValueError("Individual scenes require an independent shot sequence")
            if sum(scene.duration_seconds for scene in self.scenes) != self.duration_seconds:
                raise ValueError("Scene durations must add up to the requested film duration")
            if any(len(self.prompt + "\n\n" + scene.prompt) > 2000 for scene in self.scenes):
                raise ValueError("Shared instructions and each scene must fit 2000 characters together")
        return self
