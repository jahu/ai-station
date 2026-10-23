"""One-turn local data authority; no host paths, project IDs or arbitrary tools."""

from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.data_schema import AgentDataScope


class DataScope(AgentDataScope):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    model: str = Field(default="auto", pattern=r"^(auto|llamacpp:[0-9a-f-]{36})$")
    maximum_runtime: int = Field(default=600, ge=5, le=3600, strict=True)

    @field_validator("model")
    @classmethod
    def installed_local_model(cls, value):
        if value != "auto":
            UUID(value.split(":", 1)[1])
        return value

    def files(self):
        return AgentDataScope(input_artifact_ids=self.input_artifact_ids, max_repairs=self.max_repairs)
