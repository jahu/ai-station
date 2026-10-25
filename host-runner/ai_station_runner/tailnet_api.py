"""Operator-only typed access to an isolated native tailnet instance."""

import hashlib
import os
import platform
import threading
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner import tailnet_actions
from ai_station_runner.config import get_settings
from ai_station_runner.tailnet_install import VERSION, verified_install
from ai_station_runner.tailnet_service import TailnetManager

router = APIRouter(prefix="/v1/private-access")
_lock = threading.RLock()
_instance = None


def paths():
    settings = get_settings()
    data = settings.host_data_dir().resolve()
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if platform.system() != "Linux" or not architecture:
        raise ValueError("Private access needs Linux x64 or ARM64")
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ai-station/tailscale"
    binaries = (
        Path(settings.tailnet_binary_dir).expanduser()
        if settings.tailnet_binary_dir
        else cache / f"tailscale-{VERSION}-{architecture}"
    )
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "ai-station"
    tag = hashlib.sha256(str(data).encode()).hexdigest()[:12]
    private = (
        Path(settings.tailnet_private_dir).expanduser()
        if settings.tailnet_private_dir
        else base / f"tailnet-{tag}"
    )
    return private, binaries, architecture


def manager():
    global _instance
    private, binaries, _ = paths()
    settings = get_settings()
    canonical = private.expanduser().absolute()
    if any(
        location.is_relative_to(root.resolve()) or root.resolve().is_relative_to(location)
        for root in settings.roots()
        for location in (canonical, binaries.expanduser().absolute())
    ):
        raise ValueError("Private keys and executables must be outside every allowed filesystem root")
    key = (str(private), str(binaries), str(settings.host_data_dir().resolve()), settings.port)
    with _lock:
        if _instance is None or _instance[0] != key:
            _instance = (
                key,
                TailnetManager(private, binaries, settings.host_data_dir(), ui_port=settings.port),
            )
        return _instance[1]


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    operation: Literal["install", "start", "login", "serve_on", "stop"]
    permissions: list[str] = Field(max_length=8)
    node_id: str | None = Field(default=None, max_length=128)
    origin: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def device_scope(self):
        if self.operation == "serve_on":
            from ai_station_runner.tailnet import https_origin

            if (
                not self.node_id
                or not self.origin
                or not self.origin.startswith("https://")
                or https_origin(self.origin[8:]) != self.origin
            ):
                raise ValueError("Review the exact private endpoint")
        elif self.node_id is not None or self.origin is not None:
            raise ValueError("Only enabling HTTPS selects an endpoint")
        return self


class Inspect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    operation: Literal["install", "start", "login", "serve_on", "stop"]
    permissions: list[str] = Field(max_length=8)


def require(body):
    if body.permissions != ["manage_private_access"]:
        raise HTTPException(403, "Private operator-access permission required")


def guarded(call):
    try:
        return call()
    except (ValueError, OSError, KeyError, TypeError):
        raise HTTPException(
            409, "Private service needs inspection; no unrelated service was changed"
        ) from None


@router.get("")
def status():
    def read():
        _, binary, architecture = paths()
        try:
            verified_install(binary, architecture)
        except (ValueError, OSError, KeyError, TypeError):
            return {
                "available": True,
                "installed": False,
                "state": "not_installed",
                "serving": False,
                "version": VERSION,
            }
        return {"available": True, "installed": True, "version": VERSION, **manager().status()}

    return guarded(read)


@router.post("/actions")
def start(body: Action):
    require(body)

    def work():
        m = manager()
        rid = str(body.run_id)
        if body.operation == "start":
            state = m.start(rid)
            if state.get("canceled"):
                return {
                    "run_id": rid,
                    "phase": "canceled",
                    "service": state,
                    "process_confirmed_gone": state.get("daemon_id") != rid or state["state"] == "stopped",
                }
            return {
                "run_id": rid,
                "phase": "succeeded"
                if state["state"] not in {"starting", "unknown", "inspection_required", "stopped"}
                else "running",
                "service": state,
                "process_confirmed_gone": True,
            }
        if body.operation == "stop":
            if m.root.exists() and m.canceled(rid, "stop"):
                return {
                    "run_id": rid,
                    "phase": "canceled",
                    "service": m.status(),
                    "process_confirmed_gone": True,
                }
            if not m.root.exists():
                return {
                    "run_id": rid,
                    "phase": "succeeded",
                    "process_confirmed_gone": True,
                    "service": m.status(),
                }
            m.forget_endpoint()
            tailnet_actions.drain(m)
            result = m.stop()
            m.forget_endpoint()
            return {
                "run_id": rid,
                "phase": "succeeded"
                if result.get("stopped") or m.status()["state"] == "stopped"
                else "failed",
                "process_confirmed_gone": True,
                "service": m.status(),
            }
        return tailnet_actions.begin(m, rid, body.operation, node_id=body.node_id, origin=body.origin)

    return guarded(work)


@router.post("/inspect")
def inspect(body: Inspect):
    require(body)

    def read():
        m = manager()
        rid = str(body.run_id)
        if body.operation in {"start", "stop"}:
            state = m.status()
            if body.operation == "start":
                if state.get("daemon_id") != rid:
                    return {
                        "run_id": rid,
                        "phase": "missing",
                        "service": state,
                        "process_confirmed_gone": False,
                    }
                phase = (
                    "running"
                    if state["state"] == "starting"
                    else "succeeded"
                    if state["state"] not in {"stopped", "unknown", "inspection_required"}
                    else "failed"
                )
            else:
                phase = "succeeded" if state["state"] == "stopped" else "missing"
            return {
                "run_id": rid,
                "phase": phase,
                "service": state,
                "process_confirmed_gone": phase != "missing",
            }
        if tailnet_actions.record(m, rid)["operation"] != body.operation:
            raise ValueError("Private operation inspection scope changed")
        return tailnet_actions.inspect(m, rid)

    return guarded(read)


@router.post("/cancel")
def cancel(body: Inspect):
    require(body)

    def stop_owned():
        manager().request_cancel(str(body.run_id), body.operation)
        if body.operation == "start":
            manager().stop(only_start_run_id=str(body.run_id))
        elif body.operation not in {"stop"}:
            path = manager().root / "operations" / (str(body.run_id) + ".json")
            if path.exists() or path.is_symlink():
                if tailnet_actions.record(manager(), str(body.run_id))["operation"] != body.operation:
                    raise ValueError("Private cancellation scope changed")
                return tailnet_actions.cancel(manager(), str(body.run_id))
        return {
            "run_id": str(body.run_id),
            "phase": "canceled",
            "process_confirmed_gone": True,
            "service": manager().status(),
        }

    return guarded(stop_owned)


@router.post("/link")
def link(body: Inspect):
    require(body)
    if body.operation not in {"login", "serve_on"}:
        raise HTTPException(409, "This operation has no interactive link")

    def read():
        if tailnet_actions.record(manager(), str(body.run_id))["operation"] != body.operation:
            raise ValueError("Private interactive scope changed")
        return {"url": tailnet_actions.action_link(manager(), str(body.run_id))}

    return guarded(read)
