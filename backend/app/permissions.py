"""Capability permissions. There is no full-access flag."""

from __future__ import annotations

PROFILES: dict[str, list[str]] = {
    "read_only": ["filesystem_read", "git_read"],
    "agent_minimal": ["filesystem_read"],
    "agent_local": [],
    "agent_external_coding": [],  # Grants come from the explicitly reviewed coding tool.
    "agent_research": ["filesystem_read", "network_read"],
    "image_generation": ["filesystem_read", "workspace_write"],
    "coding_standard": [
        "filesystem_read",
        "workspace_write",
        "git_read",
        "git_write",
        "shell_project_commands",
        "python_execute",
    ],
    "coding_external": [
        "filesystem_read",
        "workspace_write",
        "git_read",
        "git_write",
        "shell_project_commands",
        "external_ai",
    ],
    "chat_local": [],
    "chat_external": ["external_ai"],
}

ALL_PERMISSIONS = sorted(
    {
        "filesystem_read",
        "workspace_write",
        "git_read",
        "git_write",
        "network_read",
        "github_read",
        "network_external",
        "shell_project_commands",
        "email_read",
        "email_send",
        "browser",
        "external_ai",
        "manage_agents",
        "manage_models",
        "manage_station",
        "memory_write",
        "project_memory_read",
    }
)


class PermissionDenied(Exception):
    pass


def permissions_for(profile: str, extra: list[str] | None = None) -> list[str]:
    if profile not in PROFILES:
        raise PermissionDenied(f"Unknown permission profile: {profile}")
    granted = list(PROFILES[profile])
    for item in extra or []:
        if item not in ALL_PERMISSIONS:
            raise PermissionDenied(f"Unknown permission: {item}")
        if item not in granted:
            granted.append(item)
    return granted


def require(granted: list[str], needed: str) -> None:
    if needed not in granted:
        raise PermissionDenied(f"Missing permission: {needed}")
