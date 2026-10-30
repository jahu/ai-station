"""Pure speech request settings shared by HTTP and persistent agents."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer


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

    @model_serializer(mode="wrap")
    def preserve_legacy_identity(self, handler):
        values = handler(self)
        if self.delivery is None:
            values.pop("delivery", None)
        return values
