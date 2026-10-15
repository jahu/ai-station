"""Validated local agent definitions; unsupported capabilities remain disabled."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from app.agent_coding_policy import CODING_TOOLS, coding_provider, external_coding
from app.agent_tools import AGENT_TOOLS, agent_tool
from app.db import utcnow
from app.http_fetch import reviewed_urls


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["none", "manual"] = "none"

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy(cls, value):
        if value is None or value == {}:
            return {"mode": "none"}
        if isinstance(value, dict) and "mode" not in value:
            return {"mode": "none"}
        return value


class NotificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on_success: StrictBool = False
    on_failure: StrictBool = False
    on_approval: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy(cls, value):
        if value is None or value == {}:
            return {}
        if isinstance(value, dict) and not any(
            key in value for key in ("on_success", "on_failure", "on_approval")
        ):
            return {"on_success": False, "on_failure": False, "on_approval": False}
        return value


class AgentGithubScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: UUID
    repository: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$", max_length=140)

    @field_validator("repository")
    @classmethod
    def canonical_repository(cls, value):
        if value.split("/")[1] in {".", ".."} or value.endswith(".git"):
            raise ValueError("Choose a canonical GitHub repository")
        return value


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


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    goal: str = Field(min_length=1, max_length=16000)
    system_prompt: str = Field(default="", max_length=8000)
    runtime: Literal["openai-compatible"] = "openai-compatible"
    provider: Literal["local-openai-compatible"] = "local-openai-compatible"
    model: str = Field(default="", max_length=200)
    github: AgentGithubScope | None = None
    data: AgentDataScope | None = None
    search_query: str = Field(default="", max_length=500)
    fetch_urls: list[str] = Field(default_factory=list, max_length=3)
    tools: list[str] = Field(default_factory=list, max_length=8)
    skills: list[str] = Field(default_factory=list, max_length=4)
    memory_scope: Literal["agent"] = "agent"
    trigger: Literal["manual", "cron", "interval", "datetime"] = "manual"
    cron_expr: str = Field(default="", max_length=120)
    interval_seconds: int | None = Field(default=None, ge=60, le=31536000)
    run_at: datetime | None = None
    permission_profile: Literal["agent_local", "agent_external_coding"] = "agent_local"
    project_id: UUID | None = None
    execution_target: Literal["container"] = "container"
    maximum_runtime: int = Field(default=600, ge=5, le=3600)
    output_expectation: str = Field(default="A concise, factual report.", max_length=4000)
    require_approval: StrictBool = False
    workflow_mode: Literal["sequential", "gated"] = "sequential"
    tool_calling: Literal["none", "bounded"] = "none"
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    notification_policy: NotificationPolicy = Field(default_factory=NotificationPolicy)
    enabled: StrictBool = False

    @model_validator(mode="after")
    def validate_definition(self):
        self.tools = list(dict.fromkeys(self.tools))
        if any(tool not in AGENT_TOOLS for tool in self.tools):
            raise ValueError("Unknown agent tool")
        if set(self.tools).intersection(CODING_TOOLS):
            if not coding_provider(self.tools) or self.tool_calling != "none":
                raise ValueError(
                    "Select one coding provider; only Local coding may add reviewed HTTP fetch, without report tool calling"
                )
            if len(self.goal) > 10000:
                raise ValueError("Coding goals must be at most 10000 characters")
            if self.enabled and external_coding(self.tools) and not self.project_id:
                raise ValueError("Choose the project this coding agent may modify before enabling it")
        if external_coding(self.tools) != (self.permission_profile == "agent_external_coding"):
            raise ValueError(
                "External coding requires its explicit external-coding permission profile; local agents cannot inherit it"
            )
        if self.data is not None and self.tools != ["python_data"]:
            raise ValueError("Data inputs belong to an exclusive local Python data agent")
        if self.enabled and self.tools == ["python_data"] and self.data is None:
            raise ValueError("Select data files before enabling the Python agent")
        self.skills = list(dict.fromkeys(self.skills))
        if self.skills:
            from app.agent_tools import effective_permissions
            from app.skills import SkillError, assert_skill_permissions, snapshot_skills

            try:
                snapshots = snapshot_skills(self.skills)
                assert_skill_permissions(snapshots, effective_permissions(self.tools))
            except SkillError as exc:
                raise ValueError(str(exc)) from exc
        if self.trigger == "cron":
            if len(self.cron_expr.split()) != 5 or not croniter.is_valid(self.cron_expr):
                raise ValueError("Use a valid five-field UTC cron expression")
            try:
                croniter(self.cron_expr, utcnow(), max_years_between_matches=5).get_next(datetime)
            except (ValueError, KeyError) as exc:
                raise ValueError("Cron must have an occurrence within five years") from exc
        elif self.cron_expr:
            raise ValueError("Cron expression requires the cron trigger")
        if (self.trigger == "interval") != (self.interval_seconds is not None):
            raise ValueError("Interval trigger requires interval_seconds; other triggers must omit it")
        if (self.trigger == "datetime") != (self.run_at is not None):
            raise ValueError("Datetime trigger requires run_at; other triggers must omit it")
        if self.run_at:
            if self.run_at.tzinfo is None:
                raise ValueError("One-shot time requires an explicit timezone")
            self.run_at = self.run_at.astimezone(timezone.utc)
        try:
            self.fetch_urls = reviewed_urls(self.fetch_urls)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if self.enabled:
            if "github_read" in self.tools and (self.github is None or self.maximum_runtime < 70):
                raise ValueError("GitHub reading needs a reviewed repository and at least 70 seconds runtime")
            if "project_memory" in self.tools and not self.project_id:
                raise ValueError("Project memory requires an explicitly linked project before activation")
            if "web_search" in self.tools and not self.search_query:
                raise ValueError("web_search requires an explicit public search query before activation")
            if {"http_fetch", "browser"}.intersection(self.tools) and not self.fetch_urls:
                raise ValueError("Page tools require 1 to 3 explicit public URLs before activation")
            if not self.model and not external_coding(self.tools):
                raise ValueError("Select a local model before enabling the agent")
            unavailable = [name for name in self.tools if not agent_tool(name).operational]
            if unavailable:
                raise ValueError("Unavailable tools prevent activation: " + ", ".join(unavailable))
            if self.run_at and self.run_at <= utcnow():
                raise ValueError("An enabled one-shot agent needs a future time")
        return self
