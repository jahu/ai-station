"""Deterministic task router. The user can override every suggestion."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RouteSuggestion:
    intent: str
    confidence: float
    capability: str
    suggested_executor: str
    suggested_project: str | None = None
    required_permissions: list[str] = field(default_factory=list)
    resource_requirements: dict = field(default_factory=dict)
    execution_mode: str = "local"
    rationale: str = ""


_IMAGE = re.compile(
    r"\b(generate|photograph|photo|image|upscale|recompose|edit (this|the|an) image)\b",
    re.IGNORECASE,
)
_CODING = re.compile(
    r"\b(fix|refactor|implement|failing tests|bug|pull request|worktree|commit)\b",
    re.IGNORECASE,
)
_AGENT = re.compile(
    r"\b(every morning|every day|every hour|create an agent|schedule|recurring)\b",
    re.IGNORECASE,
)
_SYSTEM = re.compile(r"\b(gpu|vram|nvidia|disk space|what's using|what is using)\b", re.IGNORECASE)


def route_text(text: str, project_names: list[str] | None = None) -> RouteSuggestion:
    raw = text.strip()
    lowered = raw.lower()
    project = _match_project(lowered, project_names or [])

    if lowered.startswith("/image") or _IMAGE.search(raw):
        capability = "image.generate"
        if "upscale" in lowered:
            capability = "image.upscale"
        elif "recompose" in lowered:
            capability = "image.recompose"
        elif "edit" in lowered:
            capability = "image.edit"
        return RouteSuggestion(
            intent="image",
            confidence=0.86,
            capability=capability,
            suggested_executor="photo_pipe",
            required_permissions=["filesystem_read", "workspace_write"],
            resource_requirements={"gpu": "auto"},
            rationale="Image vocabulary maps to the photo pipeline.",
        )
    if _AGENT.search(raw):
        return RouteSuggestion(
            intent="agent",
            confidence=0.84,
            capability="agent.draft",
            suggested_executor="agent_factory",
            required_permissions=["filesystem_read"],
            resource_requirements={"gpu": "none"},
            rationale="Recurring language maps to an agent draft. Drafts stay disabled.",
        )
    if _SYSTEM.search(raw):
        return RouteSuggestion(
            intent="system",
            confidence=0.8,
            capability="system.inspect",
            suggested_executor="host_runner",
            required_permissions=["filesystem_read"],
            resource_requirements={"gpu": "none"},
            rationale="Hardware question maps to telemetry.",
        )
    if _CODING.search(raw) or project:
        return RouteSuggestion(
            intent="coding",
            confidence=0.78 if project else 0.66,
            capability="coding.task",
            suggested_executor="cursor",
            suggested_project=project,
            required_permissions=[
                "filesystem_read",
                "workspace_write",
                "git_read",
                "git_write",
                "shell_project_commands",
                "external_ai",
            ],
            resource_requirements={"gpu": "none"},
            execution_mode="external",
            rationale="Software-change language maps to a Git worktree coding task.",
        )
    return RouteSuggestion(
        intent="chat",
        confidence=0.55,
        capability="chat.complete",
        suggested_executor="local_llm",
        required_permissions=[],
        resource_requirements={"gpu": "none"},
        rationale="No stronger intent matched. Chat is the default.",
    )


def _match_project(lowered: str, names: list[str]) -> str | None:
    for name in sorted(names, key=len, reverse=True):
        if name and name.lower() in lowered:
            return name
    return None
