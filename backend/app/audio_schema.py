"""Pure speech request settings shared by HTTP and persistent agents."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1000)
    reference_artifact_id: UUID
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")
