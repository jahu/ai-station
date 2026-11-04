"""Shared pure request contracts for sound workspaces, conversations and agents."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.media_translation_text import TranslationOptions


class SoundCue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    start_frame: StrictInt = Field(ge=0, le=7499)
    end_frame: StrictInt = Field(ge=1, le=7500)
    prompt: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def positive_interval(self):
        if self.end_frame <= self.start_frame:
            raise ValueError("A sound cue must end after it starts")
        return self


class EffectsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    video_artifact_id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
    cues: list[SoundCue] = Field(default_factory=list, max_length=16, exclude_if=lambda v: not v)
    negative_prompt: str = Field(default="speech, music", max_length=2000)
    steps: StrictInt = Field(default=25, ge=10, le=50)
    cfg: float = Field(default=4.5, ge=1, le=10, strict=True, allow_inf_nan=False)
    seed: StrictInt | None = Field(default=None, ge=0, le=2147483647)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")
    translation: TranslationOptions | None = None

    @model_validator(mode="after")
    def ordered_cues(self):
        previous = 0
        for cue in self.cues:
            if cue.start_frame < previous:
                raise ValueError("Sound cues must be ordered without overlapping")
            previous = cue.end_frame
        return self
