"""Separate requested immediate results from future automation definitions."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.assistant_decisions import Intent, Outcome
from app.schedule_time import ScheduleTimezone


class AutomationSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: Literal["manual", "interval", "cron", "datetime"] = "manual"
    interval_seconds: int | None = Field(default=None, ge=60, le=31536000, strict=True)
    cron_expr: str = Field(default="", max_length=120)
    run_at: AwareDatetime | None = None
    timezone: ScheduleTimezone = "UTC"

    @model_validator(mode="after")
    def consistent(self):
        if self.trigger == "interval" and self.interval_seconds is None:
            raise ValueError("An interval requires its exact number of seconds")
        if self.trigger != "interval" and self.interval_seconds is not None:
            raise ValueError("Only interval schedules accept interval_seconds")
        if self.trigger == "cron":
            from croniter import croniter

            if (
                not self.cron_expr
                or len(self.cron_expr.split()) != 5
                or not croniter.is_valid(self.cron_expr)
            ):
                raise ValueError("Use a valid five-field cron schedule")
        elif self.cron_expr:
            raise ValueError("Only cron schedules accept cron_expr")
        if (self.run_at is not None) != (self.trigger == "datetime"):
            raise ValueError("Only a one-shot datetime schedule accepts its explicit timestamp")
        return self


class AutomationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    goal: str = Field(min_length=1, max_length=4000)
    name: str = Field(default="", max_length=200)
    media_kind: Literal["image", "video", "avatar", "music", "effects", "speech"] | None = None
    schedule: AutomationSchedule = Field(default_factory=AutomationSchedule)
    image_source: Literal["none", "supplied", "latest_result"] = "none"
    source_images: list[str] = Field(default_factory=list, max_length=8)
    vary_results: bool = False
    public_query: str = Field(default="", max_length=500)
    maximum_runtime: int | None = Field(default=None, ge=5, le=86400, strict=True)

    @model_validator(mode="after")
    def image_binding(self):
        if self.image_source != "supplied" and self.source_images:
            raise ValueError("Only supplied image references have aliases before execution")
        if self.source_images and self.media_kind != "image":
            raise ValueError("This recurring reference binding is for an image agent")
        if self.image_source != "none" and self.media_kind != "image":
            raise ValueError("Only image agents use this image-source contract")
        if self.vary_results and self.image_source == "none":
            raise ValueError("Reference variations need a supplied or produced image")
        return self


class ImmediateOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "text", "image", "video", "avatar", "audio", "files", "project", "local_changes", "system_state"
    ]
    count: int = Field(default=1, ge=1, le=8, strict=True)
    description: str = Field(min_length=1, max_length=500)
    reference_mode: Literal["independent", "provided", "sequential"] = "independent"
    source_inputs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def explicit_image_binding(self):
        if self.kind == "image" and "reference_mode" not in self.model_fields_set:
            raise ValueError("Declare the image reference requirement")
        if self.kind == "text" and self.count != 1:
            raise ValueError("Use one text answer for the requested questions")
        return self


class IntentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=800)
    immediate: list[ImmediateOutcome] = Field(default_factory=list, max_length=8)
    automations: list[AutomationIntent] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def only_current_deliverables(self):
        if not self.immediate and not self.automations:
            raise ValueError("Declare the requested immediate result or automation")
        if any(item.kind == "agent_draft" for item in self.immediate):
            raise ValueError("Agent definitions belong in automations, never in immediate media")
        return self

    def canonical(self):
        goals = [Outcome.model_validate(item.model_dump()) for item in self.immediate]
        for automation in self.automations:
            goals.append(
                Outcome(
                    kind="agent_draft",
                    description=automation.goal[:500],
                    agent_media_kind=automation.media_kind,
                    automation=automation.model_dump(mode="json"),
                )
            )
        return Intent(reason=self.reason, outcomes=goals)


PLANNING_SYSTEM = """Infer the user's requested outcomes before any tool selection. Return ONLY a JSON object matching outcome_schema: reason, immediate, automations.
Interpret the CURRENT message in the actual conversation. Prior assistant questions and available asset descriptors ground follow-ups, but never grant new host/network/activation permissions. Existing available image aliases remain usable even if this message has no new upload. Do not ask for an image already in available_inputs.
IMMEDIATE contains only results to produce NOW. A picture modification means one image unless the user explicitly requests multiple pictures now. A question, explanation, fiction or an image-writing prompt needs text, not image production. An attachment alone does not request any action. Respect negation. Image outcomes explicitly declare reference_mode (provided, independent or sequential) and actual source_inputs aliases. Sequential means a later immediate image based on a produced earlier one; do not invent future aliases.
AUTOMATIONS contains definitions for work in the FUTURE. 'Change this image and then make a new version every 15 minutes using the changed result' means exactly one immediate image and one automation: media_kind=image, image_source=latest_result, interval900, vary_results=true. It does NOT mean 2, 5 or any finite number of future images to render now. Creating a recurring agent alone has no immediate media output. A future avatar means media_kind=avatar, not an immediate avatar or a drawing of an agent. Preserve the requested cadence exactly; use manual if no cadence is supplied. Convert minutes/hours to interval_seconds. A future job's output is never duplicated in immediate. Future images may use original supplied references (image_source=supplied and source_images aliases) or the requested new output (latest_result). Preserve that distinction. Agent definitions remain disabled for review.
Set name only to a useful short label. Set maximum_runtime only if the user explicitly gives an execution time limit; it is not the interval or output duration. A public_query is a short public research topic only when future work requires web research; it does not enable the draft or grant network access.
The short automation goal describes ONLY what each future execution should do. Keep any requested invariants and permitted variations generic to the actual subject; do not assume people. Schedule, image references and future execution do not belong inside the immediate visual description. Supporting research does not add a report unless explicitly requested. Text count is always1.
Contrast: "Create an agent that makes a new picture from this reference every 30 minutes" has immediate=[]; its automation uses image_source=supplied, source_images=[the provided alias], interval1800. It does not authorize making a picture before preparing the agent. "Make a picture now and create an agent that varies that result every 30 minutes" has immediate=[one image]; its automation uses image_source=latest_result, interval1800. "Explain how to create such an agent" has immediate=[text], automations=[]. Do not invent setup renders or immediate previews for an agent-only request.
"""


def validate_plan(text, context):
    import re

    plan = IntentPlan.model_validate_json(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
    aliases = {item["alias"]: item for item in context.get("inputs_and_results", [])}
    for automation in plan.automations:
        if any(aliases.get(alias, {}).get("type") != "image" for alias in automation.source_images):
            raise ValueError("Choose supplied image aliases from the current conversation catalog")
    from app.assistant_decisions import validate_intent

    canonical = plan.canonical()
    return validate_intent(canonical.model_dump_json(), context)
