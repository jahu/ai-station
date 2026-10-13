"""Typed browser dispatch and exact ownership of optional isolated containers."""

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_station_runner.config import get_settings
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.public_http import public_url
from ai_station_runner.worktrees import owned_path

PERMISSIONS = {"browser", "network_read"}
IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTAINER = re.compile(r"^[0-9a-f]{64}$")
ENTRYPOINT = ["python", "-u", "/opt/ai-station/browser_renderer.py"]


class BrowserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    urls: list[str] = Field(min_length=1, max_length=3)
    permissions: list[str] = Field(max_length=32)
    maximum_runtime: int = Field(default=165, ge=5, le=165, strict=True)

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, values):
        if len(set(values)) != len(values) or any(public_url(url) is None for url in values):
            raise ValueError("Browser requires unique reviewed public HTTP URLs")
        return values


def directory(run_id):
    return owned_path(f"runtime/browser/{UUID(run_id)}")


def save(path, payload):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as handle:
        os.chmod(temp, 0o600)
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def docker(args, *, missing_ok=False):
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Browser Docker operation could not be confirmed") from exc
    if result.returncode:
        if missing_ok and "no such" in result.stderr.lower():
            return None
        raise RuntimeError("Browser Docker operation could not be confirmed")
    if len(result.stdout) > 256 * 1024:
        raise RuntimeError("Browser Docker response exceeded its bound")
    return result.stdout.strip()


def capabilities():
    configured = get_settings().browser_image
    unavailable = {"available": False, "reason": "Build and configure the optional AI Station browser image"}
    if not re.fullmatch(r"ai-station-browser:[A-Za-z0-9_.-]+", configured):
        return unavailable
    try:
        raw = docker(["image", "inspect", configured, "--format", "{{json .}}"], missing_ok=True)
        image = json.loads(raw) if raw else {}
        config = image.get("Config") or {}
        if (
            not IMAGE.fullmatch(image.get("Id", ""))
            or config.get("Entrypoint") != ENTRYPOINT
            or config.get("User") != "1000:1000"
            or (config.get("Labels") or {}).get("ai-station.browser.protocol") != "1"
        ):
            return unavailable
        return {"available": True, "image_id": image["Id"], "protocol": 1}
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        return unavailable


def start_browser(manager, body):
    if not PERMISSIONS.issubset(body.permissions):
        raise PermissionError("Browser requires explicit browser and network_read permissions")
    root = directory(str(body.run_id))
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = root / "request.json"
        if request.exists():
            saved = load_request(str(body.run_id))
            if BrowserRequest.model_validate(saved["request"]) != body:
                raise ValueError("Run already owns another browser request")
            record = manager.inspect(str(body.run_id))
            if record["executor"] != "browser":
                raise ValueError("Unexpected browser process owner")
            return record
        try:
            manager.inspect(str(body.run_id))
        except ProcessNotOwned:
            pass
        else:
            raise ValueError("Run already owns a process")
        capability = capabilities()
        if not capability["available"]:
            raise ValueError(capability["reason"])
        digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        save(
            request,
            {"request": body.model_dump(mode="json"), "digest": digest, "image": capability["image_id"]},
        )
        return manager.start(
            run_id=str(body.run_id),
            argv=[sys.executable, "-m", "ai_station_runner.browser_job", str(body.run_id)],
            cwd=get_settings().host_data_dir().resolve(),
            executor="browser",
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": os.environ.get("HOME", ""),
                "PYTHONPATH": os.pathsep.join(sys.path),
                "AI_STATION_DATA_HOST_PATH": str(get_settings().host_data_dir().resolve()),
                "PYTHONUNBUFFERED": "1",
            },
        )


def load_request(run_id):
    saved = json.loads((directory(run_id) / "request.json").read_text())
    body = BrowserRequest.model_validate(saved["request"])
    if (
        str(body.run_id) != str(UUID(run_id))
        or saved["digest"] != hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    ):
        raise ValueError("Browser request ownership mismatch")
    return saved


def container_identity(saved, index):
    body = BrowserRequest.model_validate(saved["request"])
    if not IMAGE.fullmatch(saved["image"]):
        raise ValueError("Invalid browser image identity")
    return f"ai-station-browser-{body.run_id}-{index}", {
        "ai-station.browser.owner": str(body.run_id),
        "ai-station.browser.request": saved["digest"],
        "ai-station.browser.page": str(index),
    }


def inspect_container(saved, index, recorded_id=None):
    name, expected = container_identity(saved, index)
    raw = docker(["inspect", "--type", "container", name, "--format", "{{json .}}"], missing_ok=True)
    if not raw:
        return None
    item = json.loads(raw)
    cid = item.get("Id", "")
    labels = (item.get("Config") or {}).get("Labels") or {}
    if (
        not CONTAINER.fullmatch(cid)
        or (recorded_id and cid != recorded_id)
        or item.get("Image") != saved["image"]
        or any(labels.get(key) != value for key, value in expected.items())
    ):
        raise ValueError("Refusing a container whose browser ownership does not match")
    return item


def stop_containers(run_id):
    root = directory(run_id)
    request = root / "request.json"
    if not request.exists():
        raise ValueError("Browser request ownership missing")
    saved = load_request(run_id)
    body = BrowserRequest.model_validate(saved["request"])
    unknown = False
    with (root / "containers.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for index in range(len(body.urls)):
            path = root / f"container-{index}.json"
            if not path.exists():
                continue
            manifest = json.loads(path.read_text())
            if manifest["state"] == "removed":
                continue
            item = inspect_container(saved, index, manifest.get("id"))
            if item:
                docker(["rm", "--force", item["Id"]])
                save(path, {"state": "removed", "id": item["Id"]})
            elif manifest.get("id"):
                save(path, {"state": "removed", "id": manifest["id"]})
            else:
                # A lost create response may still hide a late daemon-side effect.
                unknown = True
    return not unknown


def cancel_browser(run_id):
    root = directory(run_id)
    save(root / "cancel.json", {"requested": True})
    return stop_containers(run_id)


def browser_report(manager, run_id):
    record = manager.inspect(run_id)
    if (
        record["executor"] != "browser"
        or record["alive"]
        or record.get("completion_pending")
        or record.get("exit_code") != 0
        or record["status"] in {"canceled", "interrupted"}
    ):
        raise ValueError("Browser has no confirmed successful completion")
    root = directory(run_id)
    saved = load_request(run_id)
    report = json.loads((root / "report.json").read_text())
    if report.get("run_id") != run_id or report.get("urls") != saved["request"]["urls"]:
        raise ValueError("Browser report ownership mismatch")
    if not stop_containers(run_id):
        raise ValueError("Browser container completion requires inspection")
    return report
