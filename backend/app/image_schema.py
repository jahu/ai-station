"""Pure typed image settings shared by HTTP, conversations and agents."""

from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictBool,
    field_validator,
    model_serializer,
    model_validator,
)

from app.media_translation_text import TranslationOptions


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    translation: TranslationOptions | None = None

    mode: Literal["t2i", "img2img", "recompose", "upscale"]
    backend: Literal["qwen", "juggernaut", "krea2"] = "qwen"
    model_id: UUID | None = None
    reference_strength: float | None = Field(default=None, ge=0, le=8, allow_inf_nan=False)
    reference_layout: Literal["aligned", "beside"] | None = None
    grounding_px: int | None = Field(default=None, ge=384, le=1024, multiple_of=64)
    _explicit_fields: set[str] = PrivateAttr(default_factory=set)
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

    @model_serializer(mode="wrap")
    def preserve_existing_image_identity(self, handler):
        values = handler(self)
        for key in ("model_id", "reference_strength", "reference_layout", "grounding_px", "translation"):
            if values.get(key) is None:
                values.pop(key, None)
        return values

    @field_validator("gpu")
    @classmethod
    def canonical_gpu(cls, value):
        return value if value == "auto" else str(int(value))

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        self._explicit_fields = set(self.model_fields_set)
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
        krea = self.backend == "krea2"
        if krea and (self.model_id is None or self.mode == "upscale"):
            raise ValueError("Krea requires a selected image model and supports Generate, Edit or Recompose")
        if krea and self.mode == "recompose" and count > 2:
            raise ValueError("Krea Recompose supports at most two references")
        if not krea and any(
            value is not None for value in (self.reference_strength, self.reference_layout, self.grounding_px)
        ):
            raise ValueError("These reference controls apply only to Krea")
        if krea and (
            (self.cfg is not None and self.cfg < 1) or (self.cfg or 1) > 10 or (self.steps or 8) > 100
        ):
            raise ValueError("Krea requires CFG 1–10 and at most 100 steps")
        if self.mode != "t2i" and self.backend not in {"qwen", "krea2"}:
            raise ValueError("Backend selection applies only to Generate")
        if not krea and (self.mode != "t2i" or self.backend != "juggernaut"):
            if self.seed is not None or self.negative:
                raise ValueError("Seed and negative prompt are supported only by Juggernaut")
        if self.mode in {"t2i", "recompose"}:
            self.width = self.width or (768 if krea else 832)
            self.height = self.height or (1024 if krea else 1216)
            self.steps = self.steps or (8 if krea else 35 if self.mode == "t2i" else 30)
            self.cfg = (
                self.cfg if self.cfg is not None else (1.0 if krea else 5.0 if self.mode == "t2i" else 6.0)
            )
            if krea and self.width * self.height > 2_097_152:
                raise ValueError("Krea output must be at most two megapixels")
        if self.mode == "img2img":
            self.max_side = self.max_side or (1024 if krea else 1216)
            self.steps = self.steps or (8 if krea else 30)
            if (self.upscale_result or self.video_prompt) and self.max_side > 2048:
                raise ValueError("Edit follow-up requires a maximum side of at most 2048")
        if self.mode == "t2i" and self.backend == "juggernaut" and self.seed is None:
            self.seed = 42
        if krea:
            self.seed = self.seed if self.seed is not None else 42
            self.cfg = self.cfg if self.cfg is not None else 1.0
            if self.mode != "t2i":
                self.reference_strength = (
                    self.reference_strength
                    if self.reference_strength is not None
                    else (4 if self.mode == "img2img" else 2)
                )
                self.reference_layout = self.reference_layout or "aligned"
                self.grounding_px = self.grounding_px or 768
        return self
