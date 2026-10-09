"""Inspect ai-station:local versus running compose containers. Never start, stop, tag or roll out."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

IMAGE = "ai-station:local"
SERVICES = ("ai-station", "worker", "scheduler")
CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
PROJECT_PREFIX = "ai-station"


def docker(args: list[str], *, missing_ok: bool = False) -> str | None:
    if not _allowed(args):
        raise RuntimeError("Refusing a Docker argument list outside station-image inspect")
    if not shutil.which("docker"):
        raise FileNotFoundError("docker")
    try:
        result = subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Docker inspect could not be confirmed") from exc
    if result.returncode:
        combined = (result.stderr or result.stdout or "").lower()
        if missing_ok and ("no such" in combined or "not found" in combined):
            return None
        raise RuntimeError("Docker inspect failed")
    if len(result.stdout) > 256 * 1024:
        raise RuntimeError("Docker inspect response exceeds its bound")
    return result.stdout.strip()


def _allowed(args: list[str]) -> bool:
    if args[:3] == ["image", "inspect", IMAGE] and args[3:] == ["--format", "{{json .}}"]:
        return True
    if (
        args[:2] == ["ps", "--filter"]
        and len(args) == 5
        and args[2] in {f"label=com.docker.compose.service={name}" for name in SERVICES}
        and args[3:] == ["--format", "{{.ID}}"]
    ):
        return True
    if (
        args[:3] == ["inspect", "--type", "container"]
        and len(args) == 6
        and CONTAINER_ID.fullmatch(args[3] or "")
        and args[4:] == ["--format", "{{json .}}"]
    ):
        return True
    return False


def inspect_tag() -> dict[str, Any]:
    raw = docker(["image", "inspect", IMAGE, "--format", "{{json .}}"], missing_ok=True)
    empty = {"name": IMAGE, "present": False, "id": None, "created": None}
    if not raw:
        return empty
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return empty
    image_id = str(payload.get("Id") or "")
    if not IMAGE_ID.fullmatch(image_id):
        return empty
    return {
        "name": IMAGE,
        "present": True,
        "id": image_id,
        "created": payload.get("Created") if isinstance(payload.get("Created"), str) else None,
    }


def running_ids(service: str) -> list[str]:
    if service not in SERVICES:
        return []
    raw = docker(
        ["ps", "--filter", f"label=com.docker.compose.service={service}", "--format", "{{.ID}}"],
        missing_ok=True,
    )
    found: list[str] = []
    for line in (raw or "").splitlines():
        item = line.strip().lower()
        if CONTAINER_ID.fullmatch(item):
            found.append(item)
    return found


def inspect_container(container_id: str, tag_id: str | None) -> dict[str, Any] | None:
    if not CONTAINER_ID.fullmatch(container_id):
        return None
    raw = docker(
        ["inspect", "--type", "container", container_id, "--format", "{{json .}}"],
        missing_ok=True,
    )
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    config = payload.get("Config") if isinstance(payload.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    service = str(labels.get("com.docker.compose.service") or "")
    project = str(labels.get("com.docker.compose.project") or "")
    if service not in SERVICES or not project.startswith(PROJECT_PREFIX):
        return None
    image_name = str(config.get("Image") or "")
    image_id = str(payload.get("Image") or "")
    if image_name != IMAGE and image_id != tag_id:
        return None
    if image_id and not IMAGE_ID.fullmatch(image_id):
        return None
    state = payload.get("State") if isinstance(payload.get("State"), dict) else {}
    name = str(payload.get("Name") or "").lstrip("/")
    return {
        "id": str(payload.get("Id") or container_id),
        "name": name,
        "service": service,
        "project": project,
        "status": str(state.get("Status") or ""),
        "image": image_name,
        "image_id": image_id or None,
        "matches_tag": bool(tag_id) and image_id == tag_id,
    }


def inspect_station_image() -> dict[str, Any]:
    try:
        tag = inspect_tag()
        containers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for service in SERVICES:
            for container_id in running_ids(service):
                if container_id in seen:
                    continue
                seen.add(container_id)
                row = inspect_container(container_id, tag.get("id"))
                if row is not None:
                    containers.append(row)
        present = [row for row in containers if row["status"] == "running"]
        matches = bool(tag["present"] and present and all(row["matches_tag"] for row in present))
        summary = _summary("available", tag, present, matches)
        return {
            "docker": "available",
            "tag": tag,
            "containers": present,
            "matches_running": matches,
            "image_rollout": "unpublished",
            "restore": "unpublished",
            "summary": summary,
        }
    except FileNotFoundError:
        return {
            "docker": "unavailable",
            "tag": {"name": IMAGE, "present": False, "id": None, "created": None},
            "containers": [],
            "matches_running": False,
            "image_rollout": "unpublished",
            "restore": "unpublished",
            "summary": (
                "Host Docker is not available to inspect ai-station:local. Image rollout stays unpublished."
            ),
        }
    except RuntimeError:
        return {
            "docker": "misconfigured",
            "tag": {"name": IMAGE, "present": False, "id": None, "created": None},
            "containers": [],
            "matches_running": False,
            "image_rollout": "unpublished",
            "restore": "unpublished",
            "summary": ("Host Docker could not inspect ai-station:local. Image rollout stays unpublished."),
        }


def _summary(docker_status: str, tag: dict[str, Any], containers: list[dict[str, Any]], matches: bool) -> str:
    if docker_status != "available":
        return "Host Docker could not inspect ai-station:local. Image rollout stays unpublished."
    if not tag["present"]:
        return "The ai-station:local tag is not present on this host. Image rollout stays unpublished."
    if not containers:
        return (
            "ai-station:local is present, but no running compose API/worker/scheduler "
            "containers use that image. Image rollout stays unpublished."
        )
    if matches:
        return (
            "Running control-plane containers use the current ai-station:local image ID. "
            "Applying a new image stays unpublished."
        )
    return (
        "Running control-plane containers do not all match the current ai-station:local "
        "image ID. Rebuild from an isolated worktree; image rollout stays unpublished."
    )
