"""Pure typed image settings shared by HTTP, conversations and agents."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["t2i", "img2img", "recompose", "upscale"]
    backend: Literal["qwen", "juggernaut"] = "qwen"
    prompt: str = Field(default="", max_length=10_000)
    prompt_style: Literal["pipeline", "prompt", "instruction"] = "pipeline"
    negative: str | None = Field(default=None, max_length=10_000)
    edit_prompt: str = Field(default="", max_length=10_000)
    width: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    height: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    steps: int | None = Field(default=None, ge=1, le=150)
    cfg: float | None = Field(default=None, ge=0, le=30, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    max_side: int | None = Field(default=None, ge=256, le=4096, multiple_of=32)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]+)$", max_length=12)
    input_artifact_ids: list[UUID] = Field(default_factory=list, max_length=8)
    upscale_result: StrictBool = False
    video_prompt: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("gpu")
    @classmethod
    def canonical_gpu(cls, value):
        return value if value == "auto" else str(int(value))

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.prompt_style == "prompt" and self.mode != "t2i":
            raise ValueError("Prompt-only styling applies to Generate")
        if self.prompt_style == "instruction" and self.mode not in {"img2img", "recompose"}:
            raise ValueError("Instruction-only styling applies to Edit and Recompose")
        if self.mode == "upscale" and self.upscale_result:
            raise ValueError("Upscale already enlarges its source; choose it only once")
        if self.video_prompt and (self.upscale_result or self.mode == "upscale"):
            raise ValueError("Choose one follow-up: Upscale or animation after generation/editing")
        count = len(self.input_artifact_ids)
        if self.mode == "t2i" and count:
            raise ValueError("Generate does not accept source images")
        if self.mode in {"img2img", "upscale"} and count != 1:
            raise ValueError("Edit and Upscale require exactly one source image")
        if self.mode == "recompose" and count < 1:
            raise ValueError("Recompose requires at least one reference image")
        if self.mode in {"t2i", "recompose"} and not self.prompt:
            raise ValueError("A prompt is required")
        if self.mode == "img2img" and not self.edit_prompt:
            raise ValueError("An edit instruction is required")
        if self.mode != "t2i" and self.backend != "qwen":
            raise ValueError("Backend selection applies only to Generate")
        if self.mode != "t2i" or self.backend != "juggernaut":
            if self.seed is not None or self.negative:
                raise ValueError("Seed and negative prompt are supported only by Juggernaut")
        if self.mode in {"t2i", "recompose"}:
            self.width = self.width or 832
            self.height = self.height or 1216
            self.steps = self.steps or (35 if self.mode == "t2i" else 30)
            self.cfg = self.cfg if self.cfg is not None else (5.0 if self.mode == "t2i" else 6.0)
        if self.mode == "img2img":
            self.max_side = self.max_side or 1216
            self.steps = self.steps or 30
            if (self.upscale_result or self.video_prompt) and self.max_side > 2048:
                raise ValueError("Edit follow-up requires a maximum side of at most 2048")
        if self.mode == "t2i" and self.backend == "juggernaut" and self.seed is None:
            self.seed = 42
        return self
