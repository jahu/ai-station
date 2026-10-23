"""Pure reviewed data-file scope shared by persistent agents and conversations."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentDataScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_artifact_ids: list[UUID] = Field(min_length=1, max_length=8)
    max_repairs: int = Field(default=1, ge=0, le=2, strict=True)

    @field_validator("input_artifact_ids")
    @classmethod
    def unique_inputs(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Data inputs must be unique")
        return values
