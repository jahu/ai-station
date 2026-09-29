"""Cursor proposal transport with isolated configuration and no enabled tools."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from ai_station_runner.coding import CodingUnavailable
from ai_station_runner.coding_files import proposal_prompt


def prepare_cursor(directory: Path, *, prompt: str, selected: list[dict], guidance: str, model: str = ""):
    binary = shutil.which("cursor-agent") or shutil.which("agent")
    if not binary:
        raise CodingUnavailable("Cursor CLI is unavailable")
    # Home/config/state never point at the user's Cursor workspace configuration.
    # Only the CLI receives its normal authentication-directory reference.
    home, workspace = directory / "home", directory / "workspace"
    config = home / ".cursor"
    workspace.mkdir(parents=True, mode=0o700)
    config.mkdir(parents=True, mode=0o700)
    # APP_DATA_DIR may itself live inside the user's Git checkout. Give the
    # provider an empty repository boundary so upward Git discovery stops here.
    subprocess.run(
        [
            "git",
            "-c",
            "init.templateDir=",
            "-c",
            "core.hooksPath=/dev/null",
            "init",
            "--quiet",
            "--initial-branch=ai-proposal",
            str(workspace),
        ],
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TEMPLATE_DIR": "",
        },
        capture_output=True,
        check=True,
        timeout=15,
    )
    (config / "cli-config.json").write_text(
        json.dumps({"permissions": {"allow": [], "deny": ["Shell(*)", "Read(**)", "Write(**)"]}})
    )
    (config / "sandbox.json").write_text(
        json.dumps(
            {
                "type": "workspace_readonly",
                "readBoundary": "workspace",
                "networkAccess": False,
                "disableTmpWrite": True,
            }
        )
    )
    message = proposal_prompt(prompt=prompt, selected=selected, guidance=guidance)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")),
        "CURSOR_CONFIG_DIR": str(config),
        "CURSOR_DATA_DIR": str(directory / "state"),
        "NO_OPEN_BROWSER": "1",
        "NO_COLOR": "1",
    }
    argv = [
        binary,
        "--print",
        "--output-format",
        "stream-json",
        "--mode",
        "ask",
        "--trust",
        "--sandbox",
        "enabled",
        "--workspace",
        str(workspace),
        "--disable-project-configs",
        "--disable-auto-update",
        "--single-turn",
        "--allowed-tools",
        "",
    ]
    if model:
        argv.extend(["--model", model])
    argv.append(message)
    return argv, env, workspace


def proposal_result(lines: list[dict]) -> tuple[str, dict]:
    results = [item for item in lines if item.get("type") == "result"]
    if len(results) != 1 or results[0].get("subtype") != "success" or results[0].get("is_error"):
        raise CodingUnavailable("Cursor did not return one successful result")
    # Tool use is outside this adapter contract even if a future provider version
    # changes the meaning of its tool allowlist. Never apply such a result.
    if any("tool" in str(item.get("type", "")).lower() for item in lines):
        raise CodingUnavailable("Cursor attempted a tool call; proposal was not applied")
    for item in lines:
        if item.get("type") == "assistant":
            blocks = item.get("message", {}).get("content", [])
            if any(not isinstance(block, dict) or block.get("type") != "text" for block in blocks):
                raise CodingUnavailable(
                    "Cursor returned a non-text assistant action; proposal was not applied"
                )
    result = results[0]
    if not isinstance(result.get("result"), str):
        raise CodingUnavailable("Cursor result is not text")
    return result["result"], {
        key: result.get(key) for key in ("session_id", "request_id", "usage", "duration_ms")
    }
