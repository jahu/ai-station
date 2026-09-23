"""Coding CLI argv builders. Missing binaries stay unavailable."""

from __future__ import annotations

import shutil


class CodingUnavailable(Exception):
    pass


def resolve_binary(executor: str) -> str:
    if executor == "cursor":
        path = shutil.which("agent") or shutil.which("cursor-agent")
    elif executor == "codex":
        path = shutil.which("codex")
    elif executor == "claude":
        path = shutil.which("claude")
    else:
        raise CodingUnavailable(f"Unknown coding executor: {executor}")
    if not path:
        raise CodingUnavailable(f"{executor} is unavailable")
    return path


def build_argv(executor: str, workspace: str, prompt: str, model: str = "") -> list[str]:
    binary = resolve_binary(executor)
    if not prompt.strip():
        raise CodingUnavailable("Prompt is required")
    if executor == "cursor":
        argv = [
            binary,
            "--print",
            "--output-format",
            "stream-json",
            "--trust",
            "--sandbox",
            "enabled",
            "--workspace",
            workspace,
        ]
        if model:
            argv += ["--model", model]
        argv.append(prompt)
        return argv
    if executor == "codex":
        argv = [binary, "exec", "--json", "--sandbox", "workspace-write", "-C", workspace]
        if model:
            argv += ["--model", model]
        argv.append(prompt)
        return argv
    if executor == "claude":
        argv = [binary, "-p", "--output-format", "stream-json", prompt]
        return argv
    raise CodingUnavailable(executor)
