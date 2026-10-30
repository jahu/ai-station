"""Pure speech request settings shared by HTTP and persistent agents."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class SpeechDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exaggeration: float = Field(default=0.8, ge=0, le=1.5, strict=True, allow_inf_nan=False)
    cfg_weight: float = Field(default=0.4, ge=0, le=1, strict=True, allow_inf_nan=False)
    temperature: float = Field(default=0.6, ge=0.05, le=1.2, strict=True, allow_inf_nan=False)


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1000)
    reference_artifact_id: UUID
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")
    delivery: SpeechDelivery | None = None
    engine: Literal["fish_s2_pro"] | None = Field(
        default=None,
        description="Choose Fish for expressive speech directions; omit for the existing Polish Chatterbox voice.",
    )
    direction: (
        Literal[
            "natural", "whisper", "happy", "sad", "afraid", "angry", "calm", "excited", "breathy", "sighing"
        ]
        | None
    ) = None
    pace: Literal["natural", "slow", "fast"] | None = None

    @model_validator(mode="after")
    def supported_delivery(self):
        if self.engine is None and (self.direction is not None or self.pace is not None):
            raise ValueError("Choose expressive speech for direction or pacing")
        if self.engine is not None and self.delivery is not None:
            raise ValueError("Chatterbox controls cannot be used with Fish")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_identity(self, handler):
        values = handler(self)
        if self.delivery is None:
            values.pop("delivery", None)
        for field in ("engine", "direction", "pace"):
            if values.get(field) is None:
                values.pop(field, None)
        return values
