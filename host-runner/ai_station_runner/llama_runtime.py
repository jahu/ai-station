"""Owned llama.cpp containers. No arbitrary Docker arguments or network endpoints."""

import fcntl
import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.config import _split, get_settings
from ai_station_runner.local_model import Completion, forward_completion
from ai_station_runner.security import PathBoundaryError, ensure_within, resolve_child
from ai_station_runner.telemetry import collect

router = APIRouter(prefix="/v1/llama")


class Load(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: UUID
    run_id: UUID
    model_path: str = Field(min_length=1, max_length=1200)
    size_bytes: int = Field(gt=0)
    mtime: float = Field(gt=0, allow_inf_nan=False)
    gpus: list[int] = Field(max_length=16)
    context_size: int = Field(default=4096, ge=512, le=262144, multiple_of=256)
    cache_type: Literal["f16", "q8_0"] = "f16"
    permissions: list[str]


def docker(*args, missing_ok=False):
    try:
        result = subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if args[0] == "logs" else subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, "Docker operation could not be confirmed") from exc
    if result.returncode:
        if missing_ok and ("No such" in (result.stderr or "") or "not found" in (result.stderr or "")):
            return None
        raise HTTPException(503, (result.stderr or "")[-3000:] or "Docker operation failed")
    if len(result.stdout) > 1024 * 1024:
        raise HTTPException(503, "Docker response exceeds its bound")
    return result.stdout.strip()


def base():
    settings = get_settings()
    root = settings.host_data_dir().resolve()
    folder = resolve_child(root, "runtime/llama")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


@contextmanager
def locked():
    with (base() / "manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def directory(instance_id):
    name = str(UUID(str(instance_id)))
    if (base() / name).is_symlink():
        raise HTTPException(409, "Runtime directory cannot be a symlink")
    return resolve_child(base(), name)


def save(folder, manifest):
    temporary = folder / "manifest.tmp"
    with temporary.open("w") as file:
        json.dump(manifest, file)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(folder / "manifest.json")
    fd = os.open(folder, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def manifest(instance_id):
    path = directory(instance_id) / "manifest.json"
    if not path.is_file() or path.is_symlink():
        raise HTTPException(404, "Managed llama.cpp instance not found")
    return json.loads(path.read_text())


def inspected(record):
    raw = docker(
        "inspect", "--type", "container", record.get("container_id") or record["name"], missing_ok=True
    )
    if raw is None:
        return None
    item = json.loads(raw)[0]
    labels = item.get("Config", {}).get("Labels", {})
    if (
        labels.get("ai-station.llama.owner") != record["owner"]
        or labels.get("ai-station.llama.request") != record["digest"]
    ):
        raise HTTPException(409, "Container ownership does not match the saved runtime")
    if record.get("container_id") and item["Id"] != record["container_id"]:
        raise HTTPException(409, "Container identity changed")
    return item


def socket_path(instance_id):
    folder = directory(instance_id)
    raw = folder / "io" / "model.sock"
    path = resolve_child(folder, "io/model.sock")
    if raw.is_symlink() or (folder / "io").is_symlink() or path.parent != folder / "io":
        raise HTTPException(409, "Runtime socket left its owned directory")
    return path


def snapshot(instance_id):
    record = manifest(instance_id)
    if record.get("request") is None:
        return {"status": "stopped", "alive": False}
    item = inspected(record)
    if item is None:
        return {"status": "stopped", "alive": False}
    state = item["State"]
    alive = bool(state["Running"])
    status = "loading" if alive or state["Status"] == "created" else "failed"
    if record.get("error") and not alive:
        status = "failed"
    if record.get("desired") == "stopped" and not alive:
        status = "stopped"
    if alive:
        try:
            with httpx.Client(
                transport=httpx.HTTPTransport(uds=str(socket_path(instance_id))), timeout=2, trust_env=False
            ) as client:
                if client.get("http://llama/health").status_code == 200:
                    status = "ready"
        except httpx.HTTPError:
            pass
    error = record.get("error") or state.get("Error", "")
    if status == "failed" and not error:
        error = docker("logs", "--tail", "40", item["Id"])[-3000:]
    return {
        "runner_id": get_settings().runner_id,
        "status": status,
        "alive": alive,
        "container_id": item["Id"],
        "pid": state.get("Pid"),
        "exit_code": state.get("ExitCode"),
        "error": error,
        "gpus": record["request"]["gpus"],
    }


@router.post("/load")
def load(body: Load):
    if not {"manage_models", "filesystem_read"}.issubset(body.permissions):
        raise HTTPException(403, "Runtime loading requires model management and filesystem read")
    with locked():
        folder = directory(body.instance_id)
        request = body.model_dump(mode="json")
        if (folder / "manifest.json").exists():
            record = manifest(body.instance_id)
            if {"cache_type": "f16", **record["request"]} != request or record.get("desired") == "stopped":
                raise HTTPException(409, "Runtime identity is immutable")
        else:
            settings = get_settings()
            try:
                model = ensure_within(Path(body.model_path), _split(settings.model_roots))
            except (PathBoundaryError, OSError) as exc:
                raise HTTPException(422, "Model is outside configured roots") from exc
            if model.suffix.lower() != ".gguf" or not model.is_file() or "," in str(model):
                raise HTTPException(422, "Choose a GGUF inside configured model roots")
            stat = model.stat()
            if stat.st_size != body.size_bytes or abs(stat.st_mtime - body.mtime) > 0.001:
                raise HTTPException(422, "Model file changed since discovery; scan it again")
            if len(set(body.gpus)) != len(body.gpus) or any(g < 0 for g in body.gpus):
                raise HTTPException(422, "Select distinct GPU indexes")
            hardware = collect(settings.host_data_dir())
            devices = {int(g["index"]): g["uuid"] for g in hardware.get("gpus", [])}
            if any(g not in devices for g in body.gpus):
                raise HTTPException(422, "A selected GPU is unavailable")
            image = docker("image", "inspect", settings.llama_image, "--format", "{{.Id}}")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
                raise HTTPException(409, "Configured llama.cpp image identity is invalid")
            folder.mkdir(mode=0o700, exist_ok=True)
            (folder / "io").mkdir(mode=0o700, exist_ok=True)
            if "," in str(folder) or len(str(folder / "io/model.sock").encode()) >= 108:
                raise HTTPException(422, "Runtime directory is too long for a private Unix socket")
            record = {
                "request": request,
                "name": f"ai-station-llama-{body.instance_id}",
                "owner": hashlib.sha256(str(base()).encode()).hexdigest(),
                "digest": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
                "image": image,
                "model": str(model),
                "devices": [devices[g] for g in body.gpus],
                "desired": "running",
            }
            save(folder, record)
        item = inspected(record)
        if item is None:
            if record.get("container_id"):
                raise HTTPException(409, "Owned container disappeared; create a new runtime")
            args = [
                "create",
                "--pull",
                "never",
                "--name",
                record["name"],
                "--label",
                "ai-station.llama.owner=" + record["owner"],
                "--label",
                "ai-station.llama.request=" + record["digest"],
                "--network",
                "none",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "512",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=128m",
                "--mount",
                f"type=bind,src={record['model']},dst=/models/model.gguf,readonly",
                "--mount",
                f"type=bind,src={folder / 'io'},dst=/runtime",
            ]
            if record["devices"]:
                args += ["--gpus", '"device=' + ",".join(record["devices"]) + '"']
            args += [
                record["image"],
                "--model",
                "/models/model.gguf",
                "--host",
                "/runtime/model.sock",
                "--alias",
                str(body.instance_id),
                "--ctx-size",
                str(body.context_size),
                "--gpu-layers",
                "all" if body.gpus else "0",
                "--parallel",
                "1",
                "--no-webui",
                # Interactive tasks need final text inside their bounded token budget.
                "--reasoning",
                "off",
                "--reasoning-budget",
                "0",
            ]
            if body.cache_type == "q8_0":
                args += [
                    "--cache-type-k",
                    "q8_0",
                    "--cache-type-v",
                    "q8_0",
                    "--flash-attn",
                    "on",
                    "--fit",
                    "off",
                ]
            if len(body.gpus) > 1:
                args += ["--split-mode", "layer", "--tensor-split", ",".join("1" for _ in body.gpus)]
            cid = docker(*args)
            if not re.fullmatch(r"[0-9a-f]{64}", cid):
                raise HTTPException(503, "Container creation identity could not be confirmed")
            record["container_id"] = cid
            save(folder, record)
            item = inspected(record)
        elif not record.get("container_id"):
            record["container_id"] = item["Id"]
            save(folder, record)
        if item["State"]["Status"] == "created" and not record.get("error"):
            try:
                docker("start", record["container_id"])
            except HTTPException as exc:
                state = inspected(record)
                if state is None or state["State"]["Running"]:
                    raise
                record["error"] = str(exc.detail)
                save(folder, record)
        return snapshot(body.instance_id)


@router.get("/{instance_id}")
def inspect(instance_id: UUID):
    with locked():
        return snapshot(instance_id)


class Stop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permissions: list[str]


@router.post("/{instance_id}/stop")
def stop(instance_id: UUID, body: Stop):
    if "manage_models" not in body.permissions:
        raise HTTPException(403, "Stopping a runtime requires model management")
    with locked():
        folder = directory(instance_id)
        if not (folder / "manifest.json").exists():
            folder.mkdir(mode=0o700, exist_ok=True)
            # A late load request must not start after cancellation won the lock.
            save(folder, {"request": None, "desired": "stopped"})
            return {"status": "stopped", "alive": False}
        record = manifest(instance_id)
        if record.get("request") is None:
            return {"status": "stopped", "alive": False}
        record["desired"] = "stopped"
        save(directory(instance_id), record)
        item = inspected(record)
        if item is not None:
            if item["State"]["Running"]:
                docker("stop", "--time", "5", item["Id"])
            docker("rm", item["Id"])
        return snapshot(instance_id)


@router.post("/{instance_id}/chat/completions")
async def completion(instance_id: UUID, body: Completion, incoming: Request):
    record = manifest(instance_id)
    if record.get("desired") != "running" or body.model != str(instance_id):
        raise HTTPException(409, "Runtime/model identity does not match")
    client = httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=str(socket_path(instance_id))),
        timeout=httpx.Timeout(300, connect=10),
        trust_env=False,
        follow_redirects=False,
    )
    return await forward_completion(body, incoming, "http://llama/v1", client, {})
