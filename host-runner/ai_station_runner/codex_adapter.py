"""Codex text proposals with an isolated read-only permission profile."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from ai_station_runner.coding import CodingUnavailable
from ai_station_runner.coding_files import proposal_prompt

# No implicit apps, browsing, commands, child agents, hooks or host skills.
DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "view_image",
    "apps",
    "plugins",
    "hooks",
    "multi_agent",
    "browser_use",
    "computer_use",
    "image_generation",
    "memories",
    "skill_search",
    "skill_mcp_dependency_install",
    "shell_snapshot",
    "daemon_auto_start",
    "code_mode",
    "code_mode_host",
    "remote_plugin",
    "workspace_dependencies",
    "goals",
    "sleep_tool",
)


def prepare_codex(directory: Path, *, prompt: str, selected: list[dict], guidance: str, model: str = ""):
    binary = shutil.which("codex")
    if not binary:
        raise CodingUnavailable("Codex CLI is unavailable")
    help_text = subprocess.run(
        [binary, "exec", "--help"], capture_output=True, text=True, timeout=10, check=True
    ).stdout
    if not all(
        flag in help_text
        for flag in ("--ignore-user-config", "--ignore-rules", "--strict-config", "--ephemeral")
    ):
        raise CodingUnavailable("Update Codex CLI to a version with isolated non-interactive configuration")
    home, workspace = directory / "home", directory / "workspace"
    home.mkdir(parents=True, mode=0o700)
    workspace.mkdir(parents=True, mode=0o700)
    # A new HOME prevents upward user config discovery. Authentication remains
    # in the CLI's existing CODEX_HOME; AI Station never reads/copies its secrets.
    auth_home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CODEX_HOME": auth_home,
        "XDG_CONFIG_HOME": str(home / ".config"),
        "NO_COLOR": "1",
    }
    for key in ("OPENAI_API_KEY",):
        if key in os.environ:
            env[key] = os.environ[key]
    argv = [
        binary,
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--color",
        "never",
        "-C",
        str(workspace),
    ]
    config = {
        "default_permissions": "ai_station_proposal",
        "permissions.ai_station_proposal.filesystem": {":minimal": "read", ":workspace_roots": "read"},
        "permissions.ai_station_proposal.network.enabled": False,
        "approval_policy": "never",
        "project_doc_max_bytes": 0,
        "web_search": "disabled",
        "features.skip_host_skill_discovery": True,
        "analytics.enabled": False,
        "suppress_unstable_features_warning": True,
    }
    for key, value in config.items():
        # Inline tables use TOML's '=' rather than JSON's ':'.
        encoded = (
            ("{" + ",".join(json.dumps(k) + "=" + json.dumps(v) for k, v in value.items()) + "}")
            if isinstance(value, dict)
            else json.dumps(value)
        )
        argv.extend(["-c", f"{key}={encoded}"])
    for feature in DISABLED_FEATURES:
        argv.extend(["--disable", feature])
    if model:
        argv.extend(["--model", model])
    argv.append(proposal_prompt(prompt=prompt, selected=selected, guidance=guidance))
    return argv, env, workspace


def proposal_result(lines: list[dict]) -> tuple[str, dict]:
    if any(item.get("type") in {"error", "turn.failed"} for item in lines):
        raise CodingUnavailable("Codex returned an error; no proposal was applied")
    completed = [item for item in lines if item.get("type") == "turn.completed"]
    messages, threads = [], []
    allowed_events = {
        "thread.started",
        "turn.started",
        "turn.completed",
        "item.started",
        "item.updated",
        "item.completed",
    }
    for event in lines:
        if event.get("type") not in allowed_events:
            raise CodingUnavailable("Codex returned an unsupported event; proposal was not applied")
        if event.get("type") == "thread.started":
            threads.append(event.get("thread_id"))
        if event.get("type") in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item", {})
            if item.get("type") not in {"agent_message", "reasoning", "error"}:
                raise CodingUnavailable("Codex attempted a tool action; proposal was not applied")
            if event["type"] == "item.completed" and item["type"] == "agent_message":
                messages.append(item.get("text"))
    if len(completed) != 1 or not messages or not isinstance(messages[-1], str):
        raise CodingUnavailable("Codex did not return one completed text proposal")
    return messages[-1], {
        "executor": "codex",
        "thread_id": threads[-1] if threads else None,
        "usage": completed[0].get("usage"),
    }
