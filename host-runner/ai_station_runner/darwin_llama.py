"""Internal native llama.cpp lifecycle candidate, not a registered Runner capability.

Reuse owned process groups, immutable SDK/models and the existing completion
proxy. Native memory admission is advisory; it is not a cgroup/no-swap promise.
"""

import fcntl
import hashlib
import json
import math
import os
import platform
import re
import stat
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner import darwin_llama_bundle as bundle
from ai_station_runner.darwin_processes import DarwinProcessManager
from ai_station_runner.environment_files import read_json
from ai_station_runner.gguf_context import inspect_context
from ai_station_runner.local_model import forward_completion
from ai_station_runner.owned_models import validate_reference, verify_owned_model
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.runtime_install import atomic_json, owned_file
from ai_station_runner.speech_environment import directory, fingerprint
from ai_station_runner.telemetry import collect

EXECUTOR = "llama_native"
PERMISSIONS = {"manage_models", "filesystem_read"}
MIB = 1024**2


class NativeLoad(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instance_id: UUID
    run_id: UUID
    bundle_operation_id: UUID
    bundle_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    architecture: Literal["arm64", "x86_64"]
    compute: Literal["cpu", "metal"]
    metal_registry_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    model_path: str = Field(max_length=100)
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=256 * 1024**3)
    mtime: float = Field(gt=0, allow_inf_nan=False)
    context_size: StrictInt = Field(default=4096, ge=512, le=262144, multiple_of=256)
    ram_mib: StrictInt = Field(ge=256, le=1048576)
    startup_deadline_at: datetime
    permissions: list[Literal["manage_models", "filesystem_read"]] = Field(max_length=2)

    @model_validator(mode="after")
    def coordinates(self):
        validate_reference(self.model_path, self.model_sha256, True)
        if self.startup_deadline_at.tzinfo is None:
            raise ValueError("Use an absolute native startup deadline")
        if (self.compute == "cpu" and self.metal_registry_id is not None) or (
            self.compute == "metal" and (self.architecture != "arm64" or not self.metal_registry_id)
        ):
            raise ValueError("Choose an explicit supported CPU/Metal device policy")
        return self


def memory_budget(size, context, profile):
    if not isinstance(profile, dict) or profile.get("source") != "gguf_header":
        raise ValueError("Native models require inspected GGUF cache geometry")
    per_token = profile.get("q8_kv_bytes_per_token")
    trained = profile.get("trained_context")
    reserve = profile.get("state_reserve_mib", 0)
    if (
        type(size) is not int
        or not 0 < size <= 256 * 1024**3
        or type(context) is not int
        or not 512 <= context <= 262144
        or context % 256
        or type(per_token) is not int
        or not 0 < per_token <= 16 * MIB
        or type(trained) is not int
        or not context <= trained <= 16777216
        or type(reserve) is not int
        or not 0 <= reserve <= 4096
    ):
        raise ValueError("Invalid native model/context memory dimensions")
    total = (size * 115 + 99) // 100 + context * per_token + (reserve + 1024) * MIB
    return (total + MIB - 1) // MIB


def command(engine, model, socket, body):
    # MTL0 is the pinned source's name for its single default Metal device.
    # Admission requires exactly one observed unified device with the frozen ID.
    return [
        str(engine / "llama-server"),
        "--model",
        str(model),
        "--host",
        str(socket),
        "--alias",
        str(body.instance_id),
        "--ctx-size",
        str(body.context_size),
        "--device",
        "none" if body.compute == "cpu" else "MTL0",
        "--gpu-layers",
        "0" if body.compute == "cpu" else "all",
        "--parallel",
        "1",
        "--no-webui",
        "--offline",
        "--fit",
        "off",
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--flash-attn",
        "on",
        "--reasoning",
        "off",
        "--reasoning-budget",
        "0",
        "--threads",
        str(min(8, max(1, os.cpu_count() or 1))),
        *(["--no-kv-offload"] if body.compute == "cpu" else []),
    ]


class NativeLlamaManager:
    def __init__(self, root, socket_root, *, processes=None):
        architecture = platform.machine()
        version = platform.mac_ver()[0]
        if (
            platform.system() != "Darwin"
            or architecture not in {"arm64", "x86_64"}
            or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version)
            or tuple(map(int, version.split("."))) < (13, 3)
        ):
            raise RuntimeError("Native llama.cpp candidate requires a matching macOS 13.3+ host")
        self.root = Path(root).resolve(strict=True)
        self.socket_root = Path(socket_root)
        if self.socket_root.resolve(strict=True) != self.socket_root:
            raise ValueError("Native socket storage cannot cross links")
        self._private_directory(self.socket_root)
        self.architecture = architecture
        runtime = self.root / "runtime"
        if runtime.is_symlink():
            raise ValueError("Native runtime storage cannot cross links")
        runtime.mkdir(mode=0o700, exist_ok=True)
        info = runtime.stat()
        if not runtime.is_dir() or info.st_uid != os.geteuid() or info.st_mode & 0o002:
            raise ValueError("Native runtime storage must remain owned")
        self.base = directory(runtime, "native-llama-instances")
        self.processes = processes if processes is not None else DarwinProcessManager(self.root)
        self._timers = {}
        self._timer_lock = threading.RLock()
        self._closed = False
        with self._locked():
            for identity, saved in self._records():
                if (
                    saved.get("request")
                    and saved.get("dispatch_started")
                    and (saved["desired"] == "stopped" or not saved.get("ready_at"))
                ):
                    self._schedule(identity)

    @staticmethod
    def _private_directory(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Native socket directories must remain private and owned")

    @contextmanager
    def _locked(self):
        with os.fdopen(owned_file(self.base / "manager.lock", os.O_CREAT | os.O_RDWR), "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def _folder(self, identity):
        path = self.base / str(UUID(str(identity)))
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Native instance storage cannot cross links")
        return path

    def _read(self, identity):
        folder = self._folder(identity)
        if not folder.exists():
            return None
        self._private_directory(folder)
        path = folder / "manifest.json"
        if not path.exists():
            raise ValueError("Inspect the existing native instance before changing it")
        value = read_json(path)
        if not {"desired", "request"}.issubset(value) or value["desired"] not in {"running", "stopped"}:
            raise ValueError("Invalid native instance journal")
        if value["request"] is not None:
            body = NativeLoad.model_validate(value["request"])
            ready = value.get("ready_at")
            if (
                str(body.instance_id) != str(identity)
                or value.get("request_hash") != fingerprint(value["request"])
                or type(value.get("dispatch_started")) is not bool
                or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("socket_root_hash", "")))
                or (
                    ready is not None
                    and (type(ready) not in {int, float} or not math.isfinite(ready) or ready <= 0)
                )
            ):
                raise ValueError("Native instance/request identity changed")
        return value

    def _save(self, identity, value):
        folder = self._folder(identity)
        if not folder.exists():
            folder.mkdir(mode=0o700)
        atomic_json(folder, "manifest.json", value)

    def _records(self):
        for folder in self.base.iterdir():
            if re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", folder.name):
                yield folder.name, self._read(folder.name)

    def _socket(self, identity, *, create=False):
        if self.socket_root.resolve(strict=True) != self.socket_root:
            raise ValueError("Native socket storage cannot cross links")
        self._private_directory(self.socket_root)
        folder = self.socket_root / str(UUID(str(identity)))
        path = folder / "model.sock"
        if len(os.fsencode(path)) >= 104 or path.is_symlink():
            raise ValueError("Use a shorter private native inference socket path")
        if create:
            folder.mkdir(mode=0o700)  # Never adopt an unknown stale socket directory.
        self._private_directory(folder)
        if folder.resolve(strict=True) != folder:
            raise ValueError("Native inference socket left its private directory")
        if path.exists():
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError("The native inference socket is not private and owned")
        return path

    def _process(self, identity, saved):
        record = self.processes.inspect(saved["request"]["run_id"])
        if (
            record["executor"] != EXECUTOR
            or record["cwd"] != str(self._folder(identity))
            or record.get("logs_suppressed") is not True
        ):
            raise ValueError("Native process ownership or privacy policy changed")
        return record

    def _admit(self, body, frozen):
        hardware = collect(self.root)
        free = (hardware.get("memory") or {}).get("available_mib")
        if type(free) not in {int, float} or not math.isfinite(free) or free <= 0:
            raise ValueError("Native available RAM is unknown")
        reserved = 0
        for identity, saved in self._records():
            if (
                identity == str(body.instance_id)
                or not saved.get("request")
                or not saved.get("dispatch_started")
            ):
                continue
            try:
                process = self._process(identity, saved)
            except ProcessNotOwned as exc:
                raise ValueError("A previous native reservation requires inspection") from exc
            if process["alive"] or process.get("completion_pending"):
                reserved += saved["request"]["ram_mib"]
                if (
                    body.compute == "metal"
                    and saved["request"]["metal_registry_id"] == body.metal_registry_id
                ):
                    raise ValueError("The native Metal device is already reserved")
        if body.ram_mib + reserved > free:
            raise ValueError("Native RAM headroom changed; existing reservations were retained")
        if body.compute == "metal":
            report = hardware.get("metal") or {}
            devices = report.get("devices") or []
            if not report.get("complete") or len(devices) != 1 or "metal" not in frozen["compiled_backends"]:
                raise ValueError(
                    "This native Metal profile requires one unambiguous compiled/observed device"
                )
            device = devices[0]
            budget = device.get("recommended_working_set_bytes")
            if (
                device.get("registry_id") != body.metal_registry_id
                or device.get("unified_memory") is not True
                or type(budget) is not int
                or budget < body.ram_mib * MIB
            ):
                raise ValueError("Native Metal identity or advisory working-set headroom changed")

    def load(self, body: NativeLoad):
        if set(body.permissions) != PERMISSIONS:
            raise HTTPException(403, "Native models require model management and filesystem read")
        request = body.model_dump(mode="json")
        request["permissions"] = sorted(body.permissions)
        identity = str(body.instance_id)
        with self._locked():
            saved = self._read(identity)
            if saved:
                if saved["desired"] == "stopped":
                    return self._snapshot(identity, saved)
                if saved["request"] != request:
                    raise ValueError("Native runtime identity is immutable")
                if saved.get("dispatch_started"):
                    return self._snapshot(identity, saved)
            if self._closed or body.architecture != self.architecture:
                raise ValueError("The native host lifecycle/architecture changed")
            if not 0 < body.startup_deadline_at.timestamp() - time.time() <= 3600:
                raise ValueError("Native startup requires a live deadline within the next hour")
            prepared = bundle.inspect(self.root, body.bundle_operation_id, body.architecture)
            if prepared["manifest_sha256"] != body.bundle_manifest_sha256:
                raise ValueError("The frozen native engine changed")
            frozen = bundle.recipe(body.architecture)
            model = verify_owned_model(self.root, body.model_path, body.model_sha256)
            info = model.stat()
            context = inspect_context(model, body.size_bytes, body.mtime)
            if (
                info.st_size != body.size_bytes
                or abs(info.st_mtime - body.mtime) > 0.001
                or memory_budget(info.st_size, body.context_size, context) != body.ram_mib
            ):
                raise ValueError("The frozen native model/memory estimate changed")
            self._admit(body, frozen)
            if saved is None:
                self._socket(identity, create=True)
                saved = {
                    "request": request,
                    "request_hash": fingerprint(request),
                    "desired": "running",
                    "dispatch_started": False,
                    "ready_at": None,
                    "socket_root_hash": hashlib.sha256(os.fsencode(self.socket_root)).hexdigest(),
                }
                self._save(identity, saved)
            socket = self._socket(identity)
            folder = self._folder(identity)
            for name in ("home", "cache"):
                directory(folder, name)
            environment = {
                "PATH": "/usr/bin:/bin",
                "HOME": str(folder / "home"),
                "TMPDIR": str(folder / "cache"),
                "LANG": "C.UTF-8",
                "HF_HUB_OFFLINE": "1",
                "GGML_BACKEND_PATH": str(self.root / prepared["relative_path"] / "engine"),
            }
            saved["dispatch_started"] = True
            self._save(identity, saved)  # Fence before any possible native exec.
            self.processes.start(
                run_id=str(body.run_id),
                executor=EXECUTOR,
                cwd=folder,
                env=environment,
                argv=command(self.root / prepared["relative_path"] / "engine", model, socket, body),
                capture_output=False,
            )
            self._schedule(identity)
            return self._snapshot(identity, saved)

    def _ready(self, identity, body):
        def metadata(client, path):
            # A native failure must not retain an unbounded response while the
            # manager's reservation lock is held.
            data = bytearray()
            deadline = time.monotonic() + 2
            with client.stream("GET", "http://llama" + path) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("Unexpected native readiness encoding")
                for chunk in response.iter_raw():
                    data.extend(chunk)
                    if len(data) > 65536 or time.monotonic() > deadline:
                        raise ValueError("Native readiness metadata exceeds its bound")
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("Native readiness metadata requires an object")
            return value

        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(self._socket(identity))),
            timeout=0.5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            with client.stream("GET", "http://llama/health") as response:
                if response.status_code != 200:
                    return False
            models = metadata(client, "/v1/models").get("data")
            settings = metadata(client, "/props").get("default_generation_settings") or {}
        if (
            not isinstance(models, list)
            or len(models) != 1
            or not isinstance(models[0], dict)
            or models[0].get("id") != identity
        ):
            raise ValueError("The native inference model alias changed")
        if (
            not isinstance(settings, dict)
            or type(settings.get("n_ctx")) is not int
            or settings["n_ctx"] != body.context_size
        ):
            raise ValueError("The native inference context differs from its reservation")
        return True

    def _snapshot(self, identity, saved):
        if saved["request"] is None:
            return {"status": "stopped", "alive": False, "inference_qualified": False}
        body = NativeLoad.model_validate(saved["request"])
        if not saved.get("dispatch_started"):
            return {
                "status": "stopped" if saved["desired"] == "stopped" else "interrupted",
                "alive": False,
                "safe_to_resume": saved["desired"] != "stopped",
                "inference_qualified": False,
            }
        try:
            process = self._process(identity, saved)
        except ProcessNotOwned:
            return {"status": "inspection_required", "alive": None, "inference_qualified": False}
        alive = process["alive"] or process.get("completion_pending", False)
        if alive and saved["desired"] == "stopped":
            # A replacement owner must deliver an already-persisted Stop even
            # if the first owner disappeared before its signal was sent.
            process = self.processes.cancel(str(body.run_id))
            alive = process["alive"] or process.get("completion_pending", False)
        status = "stopping" if saved["desired"] == "stopped" and alive else "loading" if alive else "failed"
        if saved["desired"] == "stopped" and not alive:
            status = "failed" if saved.get("error") else "stopped"
        if alive and saved["desired"] == "running":
            if not saved["ready_at"] and time.time() >= body.startup_deadline_at.timestamp():
                saved.update(desired="stopped", error="Native startup deadline exceeded")
                self._save(identity, saved)
                self.processes.cancel(str(body.run_id))
                return self._snapshot(identity, saved)
            if saved["socket_root_hash"] != hashlib.sha256(os.fsencode(self.socket_root)).hexdigest():
                return {"status": "inspection_required", "alive": True, "inference_qualified": False}
            try:
                if self._ready(identity, body):
                    status = "ready"
                    if not saved["ready_at"]:
                        saved["ready_at"] = time.time()
                        self._save(identity, saved)
            except httpx.HTTPError:
                pass
            except (ValueError, TypeError, AttributeError):
                saved.update(desired="stopped", error="Native readiness metadata does not match")
                self._save(identity, saved)
                self.processes.cancel(str(body.run_id))
                return self._snapshot(identity, saved)
        return {
            "status": status,
            "alive": bool(alive),
            "pid": process["pid"],
            "exit_code": process.get("exit_code"),
            "error": saved.get("error") or ("Native model process exited" if status == "failed" else None),
            "compute_target": body.compute,
            "n_ctx": body.context_size if status == "ready" else None,
            "ram_mib": body.ram_mib,
            "memory_enforcement": "admission_only",
            "zero_swap_guaranteed": False,
            "inference_qualified": False,
        }

    def inspect(self, identity):
        identity = str(UUID(str(identity)))
        with self._locked():
            saved = self._read(identity)
            if saved is None:
                raise KeyError("Native instance is not owned")
            return self._snapshot(identity, saved)

    def stop(self, identity, permissions):
        if "manage_models" not in permissions:
            raise HTTPException(403, "Native Stop requires model management")
        identity = str(UUID(str(identity)))
        with self._locked():
            saved = self._read(identity)
            if saved is None:
                saved = {"request": None, "desired": "stopped"}
            saved["desired"] = "stopped"
            self._save(identity, saved)
            if saved["request"] and saved.get("dispatch_started"):
                self._schedule(identity)
            return self._snapshot(identity, saved)

    async def completion(self, identity, body, incoming):
        identity = str(UUID(str(identity)))
        if body.model != identity or any(isinstance(item.content, list) for item in body.messages):
            raise ValueError("Native text model/attachment identity does not match")
        if self.inspect(identity)["status"] != "ready":
            raise ValueError("The owned native model is not ready")
        client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(self._socket(identity))),
            timeout=httpx.Timeout(300, connect=5),
            trust_env=False,
            follow_redirects=False,
        )
        return await forward_completion(body, incoming, "http://llama/v1", client, {})

    def _schedule(self, identity):
        with self._timer_lock:
            if self._closed or identity in self._timers:
                return
            timer = threading.Timer(0.2, self._tick, (identity,))
            timer.daemon = True
            self._timers[identity] = timer
            timer.start()

    def _tick(self, identity):
        with self._timer_lock:
            self._timers.pop(identity, None)
            if self._closed:
                return
        try:
            if self.inspect(identity)["status"] in {"loading", "stopping", "inspection_required"}:
                self._schedule(identity)
        except OSError:
            # Transient observation/signal failure must not lose a durable Stop
            # or startup deadline. Every retry revalidates process ownership.
            self._schedule(identity)
        except (ValueError, KeyError):
            # Keep the dispatch fence/reservation; inspection never means gone.
            pass

    def close(self):
        """Detach observers for owner replacement, without killing owned models."""
        with self._timer_lock:
            self._closed = True
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
