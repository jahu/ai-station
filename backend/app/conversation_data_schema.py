"""One-turn local data authority; no host paths, project IDs or arbitrary tools."""

from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_serializer,
    model_validator,
)

from app.data_schema import AgentDataScope, ResearchDataScope
from app.http_fetch import reviewed_urls


class DataResearchSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    search_query: str = Field(default="", max_length=500)
    fetch_urls: list[str] = Field(default_factory=list, max_length=3)
    read_search_pages: StrictBool = False
    render_pages: StrictBool = False

    @field_validator("fetch_urls")
    @classmethod
    def public_sources(cls, values):
        return reviewed_urls(values)

    @model_validator(mode="after")
    def selected_sources(self):
        if not self.search_query and not self.fetch_urls:
            raise ValueError("Review a public search query or public URLs")
        if self.read_search_pages and not self.search_query:
            raise ValueError("Reading search pages requires a reviewed public query")
        if self.render_pages and not self.fetch_urls:
            raise ValueError("Rendering data pages requires explicit reviewed public URLs")
        return self

    @model_serializer(mode="wrap")
    def preserve_static_identity(self, handler):
        value = handler(self)
        if not self.render_pages:
            value.pop("render_pages", None)
        return value

    def tools(self):
        return (
            (["web_search"] if self.search_query else [])
            + (["search_pages"] if self.read_search_pages else [])
            + (["browser" if self.render_pages else "http_fetch"] if self.fetch_urls else [])
        )


class DataScope(AgentDataScope):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    input_artifact_ids: list[UUID] = Field(default_factory=list, max_length=8)
    research: DataResearchSelection | None = None
    model: str = Field(default="auto", pattern=r"^(auto|llamacpp:[0-9a-f-]{36})$")
    maximum_runtime: int = Field(default=600, ge=5, le=3600, strict=True)

    @field_validator("model")
    @classmethod
    def installed_local_model(cls, value):
        if value != "auto":
            UUID(value.split(":", 1)[1])
        return value

    @model_validator(mode="after")
    def inputs_or_sources(self):
        if self.research is not None:
            ResearchDataScope(input_artifact_ids=self.input_artifact_ids, max_repairs=self.max_repairs)
        elif not self.input_artifact_ids:
            raise ValueError("Choose inspected data files or explicit public research")
        return self

    @model_serializer(mode="wrap")
    def preserve_file_only_identity(self, handler):
        value = handler(self)
        if self.research is None:
            value.pop("research", None)
        return value

    def files(self):
        kind = ResearchDataScope if self.research is not None else AgentDataScope
        return kind(input_artifact_ids=self.input_artifact_ids, max_repairs=self.max_repairs)
