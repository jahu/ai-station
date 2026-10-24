"""Pure reviewed data-file scope shared by persistent agents and conversations."""

from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator


class AgentDataScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_empty_analysis: ClassVar[bool] = False
    input_artifact_ids: list[UUID] = Field(default_factory=list, max_length=8)
    max_repairs: int = Field(default=1, ge=0, le=2, strict=True)
    operation: Literal["analyze", "create"] = "analyze"

    @model_validator(mode="after")
    def explicit_input_contract(self):
        if self.operation == "create":
            if self.input_artifact_ids:
                raise ValueError("Create files uses instructions; remove selected inputs or choose analysis")
        elif not self.input_artifact_ids and not self.allow_empty_analysis:
            raise ValueError("Select data files or explicitly choose file creation")
        return self

    @model_serializer(mode="wrap")
    def preserve_analysis_identity(self, handler):
        value = handler(self)
        if self.operation == "analyze":
            value.pop("operation", None)
        return value

    @field_validator("input_artifact_ids")
    @classmethod
    def unique_inputs(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Data inputs must be unique")
        return values


class ResearchDataScope(AgentDataScope):
    """Optional files only when an AgentSettings definition grants reviewed research/memory context."""

    allow_empty_analysis: ClassVar[bool] = True
    input_artifact_ids: list[UUID] = Field(default_factory=list, max_length=7)
