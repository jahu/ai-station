"""Owned llama.cpp containers. No arbitrary Docker arguments or network endpoints."""

import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_serializer, model_validator

from ai_station_runner.config import _split, get_settings
from ai_station_runner.local_model import CodingCompletion, forward_completion
from ai_station_runner.native_llama_request import NativeModelLoad
from ai_station_runner.security import PathBoundaryError, ensure_within, resolve_child
from ai_station_runner.telemetry import collect
from ai_station_runner.unix_sockets import unix_address
from ai_station_runner.vision_messages import VisionCompletion

router = APIRouter(prefix="/v1/llama")


class Projector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1200)
    size_bytes: int = Field(ge=1)
    mtime: float = Field(allow_inf_nan=False)


class Load(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: UUID
    run_id: UUID
    model_path: str = Field(min_length=1, max_length=1200)
    app_owned: StrictBool = False
    model_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    mtime: float = Field(gt=0, allow_inf_nan=False)
    gpus: list[int] = Field(max_length=16)
    context_size: int = Field(default=4096, ge=512, le=262144, multiple_of=256)
    cache_type: Literal["f16", "q8_0"] = "f16"
    projector: Projector | None = None
    permissions: list[str]
    runtime_profile: Literal["llamacpp-cpu-linux-amd64-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    ram_mib: StrictInt | None = Field(default=None, ge=256, le=65536, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def coordinate(self):
        from ai_station_runner.owned_models import validate_reference

        validate_reference(self.model_path, self.model_sha256, self.app_owned)
        if self.runtime_profile:
            from ai_station_runner import cpu_runtime_profile as cpu

            if (
                not self.app_owned
                or self.gpus
                or self.projector
                or self.cache_type != "q8_0"
                or self.context_size != cpu.DEFAULT_CONTEXT
                or self.ram_mib is None
            ):
                raise ValueError("Managed CPU requires owned weights, its fixed context/cache and RAM budget")
        elif self.ram_mib is not None:
            raise ValueError("A managed RAM budget requires its explicit CPU profile")
        return self

    @model_serializer(mode="wrap")
    def legacy_identity(self, handler):
        value = handler(self)
        if not self.app_owned:
            value.pop("app_owned", None)
            value.pop("model_sha256", None)
        return value


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
    cpu = record.get("request", {}).get("runtime_profile")
    if cpu:
        budget = record["request"]["ram_mib"] * 1024**2
        host = item.get("HostConfig", {})
        env = item.get("Config", {}).get("Env", [])
        if (
            host.get("Memory") != budget
            or host.get("MemorySwap") != budget
            or host.get("DeviceRequests")
            or "CUDA_VISIBLE_DEVICES=-1" not in env
            or "NVIDIA_VISIBLE_DEVICES=void" not in env
        ):
            raise HTTPException(409, "The owned CPU container memory/device policy changed")
    return item


def socket_path(instance_id):
    folder = directory(instance_id)
    raw = folder / "io" / "model.sock"
    path = resolve_child(folder, "io/model.sock")
    if raw.is_symlink() or (folder / "io").is_symlink() or path.parent != folder / "io":
        raise HTTPException(409, "Runtime socket left its owned directory")
    return path


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def query_runtime_metadata(client) -> dict:
    """Read running context from llama.cpp. Never persist or return the chat template."""
    observed = {}

    def take(source, *keys):
        if not isinstance(source, dict):
            return
        for key in keys:
            value = _positive_int(source.get(key))
            if value is not None:
                observed[key] = value

    try:
        response = client.get("http://llama/v1/models")
        if response.status_code == 200:
            payload = response.json()
            entries = payload.get("data") or payload.get("models") or []
            item = (
                entries[0] if isinstance(entries, list) and entries and isinstance(entries[0], dict) else {}
            )
            take(item, "n_ctx", "n_ctx_train", "n_params")
            take(
                item.get("meta") if isinstance(item.get("meta"), dict) else {},
                "n_ctx",
                "n_ctx_train",
                "n_params",
            )
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    try:
        response = client.get("http://llama/props")
        if response.status_code == 200:
            payload = response.json()
            settings = payload.get("default_generation_settings")
            template = payload.get("chat_template")
            if isinstance(template, str) and len(template) <= 262144:
                observed["template_sha256"] = hashlib.sha256(template.encode()).hexdigest()
            take(settings if isinstance(settings, dict) else {}, "n_ctx")
            take(payload, "n_ctx_train")
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    return observed


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
    observed = {}
    if alive:
        try:
            with (
                unix_address(socket_path(instance_id)) as address,
                httpx.Client(
                    transport=httpx.HTTPTransport(uds=address), timeout=2, trust_env=False
                ) as client,
            ):
                if client.get("http://llama/health").status_code == 200:
                    status = "ready"
                    observed = query_runtime_metadata(client)
        except httpx.HTTPError:
            pass
    error = record.get("error") or state.get("Error", "")
    if status == "failed" and not error:
        error = docker("logs", "--tail", "40", item["Id"])[-3000:]
    result = {
        "runner_id": get_settings().runner_id,
        "status": status,
        "alive": alive,
        "container_id": item["Id"],
        "pid": state.get("Pid"),
        "exit_code": state.get("ExitCode"),
        "error": error,
        "gpus": record["request"]["gpus"],
    }
    result["image_id"] = record["image"]
    for key in ("n_ctx", "n_ctx_train", "n_params", "template_sha256"):
        if key in observed:
            result[key] = observed[key]
    return result


@router.post("/load")
def load(body: Load | NativeModelLoad):
    if isinstance(body, NativeModelLoad):
        from ai_station_runner.native_llama_api import load as native_load

        return native_load(body)
    if sys.platform != "linux":
        raise HTTPException(503, "Container llama.cpp profiles require a Linux Host Runner")
    if not {"manage_models", "filesystem_read"}.issubset(body.permissions):
        raise HTTPException(403, "Runtime loading requires model management and filesystem read")
    with locked():
        folder = directory(body.instance_id)
        request = body.model_dump(mode="json")
        if (folder / "manifest.json").exists():
            record = manifest(body.instance_id)
            saved = record.get("request")
            if (
                saved is None
                or {"cache_type": "f16", "projector": None, **saved} != request
                or record.get("desired") == "stopped"
            ):
                raise HTTPException(409, "Runtime identity is immutable")
        else:
            settings = get_settings()
            if body.app_owned:
                from ai_station_runner.owned_models import owned_model

                model = owned_model(body.model_path, body.model_sha256)
            else:
                try:
                    model = ensure_within(Path(body.model_path), _split(settings.model_roots))
                except (PathBoundaryError, OSError) as exc:
                    raise HTTPException(422, "Model is outside configured roots") from exc
            if (
                (not body.app_owned and model.suffix.lower() != ".gguf")
                or not model.is_file()
                or "," in str(model)
            ):
                raise HTTPException(422, "Choose a GGUF inside configured model roots")
            stat = model.stat()
            if stat.st_size != body.size_bytes or abs(stat.st_mtime - body.mtime) > 0.001:
                raise HTTPException(422, "Model file changed since discovery; scan it again")
            projector = None
            if body.projector is not None:
                try:
                    projector = ensure_within(Path(body.projector.path), _split(settings.model_roots))
                except (PathBoundaryError, OSError) as exc:
                    raise HTTPException(422, "Projector is outside configured model roots") from exc
                if projector.suffix.lower() != ".gguf" or not projector.is_file() or "," in str(projector):
                    raise HTTPException(422, "Choose an installed GGUF projector")
                observed = projector.stat()
                if (
                    observed.st_size != body.projector.size_bytes
                    or abs(observed.st_mtime - body.projector.mtime) > 0.001
                ):
                    raise HTTPException(422, "Projector changed since discovery; scan it again")
            if len(set(body.gpus)) != len(body.gpus) or any(g < 0 for g in body.gpus):
                raise HTTPException(422, "Select distinct GPU indexes")
            hardware = collect(settings.host_data_dir())
            devices = {int(g["index"]): g["uuid"] for g in hardware.get("gpus", [])}
            if any(g not in devices for g in body.gpus):
                raise HTTPException(422, "A selected GPU is unavailable")
            from ai_station_runner.runtime_setup import image_observation

            if body.runtime_profile:
                from ai_station_runner import cpu_runtime_profile as cpu
                from ai_station_runner.gguf_context import inspect_context

                if not cpu.QUALIFIED:
                    raise HTTPException(409, "Managed CPU execution is still being qualified")
                checked = inspect_context(model, body.size_bytes, body.mtime)
                budget = cpu.memory_budget_mib(body.size_bytes, body.context_size, checked)
                if budget != body.ram_mib:
                    raise HTTPException(422, "The managed CPU memory budget changed")
                free = (hardware.get("memory") or {}).get("available_mib")
                if type(free) not in {int, float} or not math.isfinite(free) or not 0 < budget <= free:
                    raise HTTPException(422, "Available RAM changed before managed CPU launch")
                _, image = image_observation(app_owned=True, runtime_profile=body.runtime_profile)
            else:
                _, image = image_observation(app_owned=body.app_owned)
            if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
                raise HTTPException(409, "Configured llama.cpp image identity is invalid")
            folder.mkdir(mode=0o700, exist_ok=True)
            (folder / "io").mkdir(mode=0o700, exist_ok=True)
            if "," in str(folder):
                raise HTTPException(422, "Runtime directory cannot contain a comma")
            record = {
                "request": request,
                "name": f"ai-station-llama-{body.instance_id}",
                "owner": hashlib.sha256(str(base()).encode()).hexdigest(),
                "digest": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
                "image": image,
                "model": str(model),
                "projector": str(projector) if projector else None,
                "devices": [devices[g] for g in body.gpus],
                "desired": "running",
            }
            save(folder, record)
        item = inspected(record)
        if item is None:
            if record.get("request", {}).get("app_owned"):
                from ai_station_runner.owned_models import owned_model

                current = owned_model(body.model_path, body.model_sha256)
                observed = current.stat()
                if (
                    str(current) != record["model"]
                    or observed.st_size != body.size_bytes
                    or abs(observed.st_mtime - body.mtime) > 0.001
                ):
                    raise HTTPException(422, "App-owned model changed before container creation")
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
            if body.runtime_profile:
                args += [
                    "--memory",
                    str(body.ram_mib) + "m",
                    "--memory-swap",
                    str(body.ram_mib) + "m",
                    "--cpus",
                    str(min(8, max(1, os.cpu_count() or 1))),
                    "--env",
                    "CUDA_VISIBLE_DEVICES=-1",
                    "--env",
                    "NVIDIA_VISIBLE_DEVICES=void",
                ]
            if record["devices"]:
                args += ["--gpus", '"device=' + ",".join(record["devices"]) + '"']
            if record.get("projector"):
                args += [
                    "--mount",
                    f"type=bind,src={record['projector']},dst=/models/projector.gguf,readonly",
                ]
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
            if body.runtime_profile:
                args += ["--threads", str(min(8, max(1, os.cpu_count() or 1)))]
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
            if record.get("projector"):
                args += ["--mmproj", "/models/projector.gguf"]
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
    if sys.platform == "darwin":
        from ai_station_runner.native_llama_api import call

        return call("inspect", instance_id)
    with locked():
        return snapshot(instance_id)


class Stop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permissions: list[str]


@router.post("/{instance_id}/stop")
def stop(instance_id: UUID, body: Stop):
    if sys.platform == "darwin":
        from ai_station_runner.native_llama_api import call

        return call("stop", instance_id, body.permissions)
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
async def completion(instance_id: UUID, body: VisionCompletion, incoming: Request):
    if sys.platform == "darwin":
        from ai_station_runner.native_llama_api import completion as native_completion

        return await native_completion(instance_id, body, incoming)
    record = manifest(instance_id)
    if record.get("desired") != "running" or body.model != str(instance_id):
        raise HTTPException(409, "Runtime/model identity does not match")
    if any(isinstance(item.content, list) for item in body.messages) and not record.get("projector"):
        raise HTTPException(409, "Load this model with its vision projector before sending images")
    with unix_address(socket_path(instance_id)) as address:
        client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=address),
            timeout=httpx.Timeout(300, connect=10),
            trust_env=False,
            follow_redirects=False,
        )
        # forward_completion establishes the connection before returning its
        # response iterator. The connected socket then outlives this directory FD.
        return await forward_completion(body, incoming, "http://llama/v1", client, {})


@router.post("/{instance_id}/coding/completions")
async def coding_completion(instance_id: UUID, body: CodingCompletion, incoming: Request):
    # Reuse the exact owned-runtime identity, private transport and disconnect handling.
    return await completion(instance_id, body, incoming)
