"""Validated local agent definitions; unsupported capabilities remain disabled."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.agent_tools import AGENT_TOOLS, agent_tool
from app.db import utcnow
from app.http_fetch import reviewed_urls


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    goal: str = Field(min_length=1, max_length=16000)
    system_prompt: str = Field(default="", max_length=8000)
    runtime: Literal["openai-compatible"] = "openai-compatible"
    provider: Literal["local-openai-compatible"] = "local-openai-compatible"
    model: str = Field(default="", max_length=200)
    search_query: str = Field(default="", max_length=500)
    fetch_urls: list[str] = Field(default_factory=list, max_length=3)
    tools: list[str] = Field(default_factory=list, max_length=6)
    skills: list[str] = Field(default_factory=list, max_length=4)
    memory_scope: Literal["agent"] = "agent"
    trigger: Literal["manual", "cron", "interval", "datetime"] = "manual"
    cron_expr: str = Field(default="", max_length=120)
    interval_seconds: int | None = Field(default=None, ge=60, le=31536000)
    run_at: datetime | None = None
    permission_profile: Literal["agent_local"] = "agent_local"
    project_id: UUID | None = None
    execution_target: Literal["container"] = "container"
    maximum_runtime: int = Field(default=600, ge=5, le=3600)
    output_expectation: str = Field(default="A concise, factual report.", max_length=4000)
    enabled: StrictBool = False

    @model_validator(mode="after")
    def validate_definition(self):
        self.tools = list(dict.fromkeys(self.tools))
        if any(tool not in AGENT_TOOLS for tool in self.tools):
            raise ValueError("Unknown agent tool")
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
            if "web_search" in self.tools and not self.search_query:
                raise ValueError("web_search requires an explicit public search query before activation")
            if "http_fetch" in self.tools and not self.fetch_urls:
                raise ValueError("http_fetch requires 1 to 3 explicit public URLs before activation")
            if not self.model:
                raise ValueError("Select a local model before enabling the agent")
            unavailable = [name for name in self.tools if not agent_tool(name).operational]
            if unavailable:
                raise ValueError("Unavailable tools prevent activation: " + ", ".join(unavailable))
            if self.run_at and self.run_at <= utcnow():
                raise ValueError("An enabled one-shot agent needs a future time")
        return self
