"""Read-only capability checks. Status is never invented."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx


def check(name: str, status: str, detail: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail}


def command_version(binary: str, args: list[str] | None = None) -> dict:
    path = shutil.which(binary)
    if not path:
        return check(binary, "unavailable", "Not on PATH")
    try:
        completed = subprocess.run(
            [path, *(args or ["--version"])],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return check(binary, "misconfigured", str(exc))
    text = (completed.stdout or completed.stderr).strip().splitlines()
    detail = text[0] if text else path
    if completed.returncode != 0:
        return check(binary, "misconfigured", f"exit {completed.returncode}: {detail}")
    return check(binary, "available", detail)


def file_check(name: str, path: str) -> dict:
    if not path:
        return check(name, "unavailable", "Path is not configured")
    candidate = Path(path)
    if candidate.is_file():
        return check(name, "available", str(candidate))
    return check(name, "misconfigured", f"Missing file: {candidate}")


def directory_check(name: str, path: str) -> dict:
    if not path:
        return check(name, "unavailable", "Path is not configured")
    candidate = Path(path)
    if candidate.is_dir():
        return check(name, "available", str(candidate))
    return check(name, "misconfigured", f"Missing directory: {candidate}")


def http_check(name: str, url: str) -> dict:
    if not url:
        return check(name, "unavailable", "Endpoint is not configured")
    try:
        response = httpx.get(url.rstrip("/") + "/models", timeout=3.0)
    except httpx.HTTPError as exc:
        return check(name, "unavailable", str(exc))
    if response.status_code >= 400:
        return check(name, "misconfigured", f"HTTP {response.status_code}")
    return check(name, "available", url)


def collect_diagnostics(settings) -> dict:
    checks = [
        command_version("docker"),
        command_version("docker", ["compose", "version"]) | {"name": "docker compose"},
        _nvidia_toolkit(),
        command_version("nvidia-smi"),
        file_check("photo_pipe", settings.photo_script),
        file_check("chatterbox_script", settings.chatterbox_script),
        file_check("chatterbox_python", settings.chatterbox_python),
        file_check("echomimic_python", settings.echomimic_python),
        file_check(
            "echomimic_entry",
            str(Path(settings.echomimic_dir) / "infer_flash.py") if settings.echomimic_dir else "",
        ),
        directory_check("echomimic_models", settings.echomimic_models),
        file_check("photo python", settings.photo_python),
        file_check("sd-cli", settings.sd_cli),
        http_check("llama.cpp / OpenAI-compatible endpoint", settings.llm_base_url),
        command_version("codex"),
        _cursor(),
        command_version("claude"),
        command_version("git"),
        command_version("gh"),
        _node(settings),
    ]
    for root in settings.model_roots.split(":"):
        if root.strip():
            checks.append(directory_check(f"model root {root}", root.strip()))
    data = settings.host_data_dir()
    checks.append(directory_check("application data", str(data)))
    if data.exists():
        usage = __import__("shutil").disk_usage(data)
        checks.append(check("free space", "available", f"{usage.free} bytes free"))
    else:
        checks.append(check("free space", "unknown", "Application data directory is missing"))
    gpus = []
    try:
        from ai_station_runner.telemetry import gpus as read_gpus

        gpus = read_gpus()
    except Exception as exc:
        checks.append(check("NVIDIA GPU detection", "unknown", str(exc)))
    else:
        if gpus:
            checks.append(check("NVIDIA GPU detection", "available", f"{len(gpus)} GPU(s)"))
        else:
            checks.append(check("NVIDIA GPU detection", "unavailable", "nvidia-smi returned no GPUs"))
    from ai_station_runner.browser_runs import capabilities as browser_capabilities

    browser = browser_capabilities()
    checks.append(
        check(
            "browser renderer",
            "available" if browser["available"] else "unavailable",
            browser.get("image_id") or browser["reason"],
        )
    )
    return {"checks": checks, "gpus": gpus}


def _nvidia_toolkit() -> dict:
    if shutil.which("nvidia-container-cli"):
        return check("nvidia-container-cli", "available", shutil.which("nvidia-container-cli") or "")
    return check("nvidia-container-cli", "unavailable", "NVIDIA Container Toolkit CLI not found")


def _node(settings) -> dict:
    from ai_station_runner.gitops import GitError
    from ai_station_runner.node_runtime import node_runtime

    try:
        runtime = node_runtime(settings.host_data_dir() / "worktrees", prefix=settings.node_prefix)
        versions = runtime.describe(
            {"HOME": str(runtime.node.parent), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        )
        return check(
            "Node/npm", "available", f"Node {versions['node_version']} · npm {versions['npm_version']}"
        )
    except (OSError, ValueError, RuntimeError, GitError, subprocess.SubprocessError) as exc:
        return check("Node/npm", "misconfigured" if settings.node_prefix else "unavailable", str(exc))


def _cursor() -> dict:
    path = shutil.which("agent") or shutil.which("cursor-agent")
    if not path:
        return check("cursor agent", "unavailable", "agent CLI not on PATH")
    return check("cursor agent", "available", path)
