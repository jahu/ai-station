"""Typed private Runner dispatch and duplex proxy for owned live sessions."""

import asyncio
import contextlib
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, WebSocket

from ai_station_runner import live_environment, runtime_install
from ai_station_runner.config import get_settings
from ai_station_runner.environment_files import read_json
from ai_station_runner.live_contract import NAME, RAM_MIB, LiveRequest
from ai_station_runner.live_hardware import compatible_gpus
from ai_station_runner.live_ipc import read_async, write_async
from ai_station_runner.live_protocol import decode
from ai_station_runner.memory_scope import available, scope_environment, scope_prefix
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.telemetry import collect
from ai_station_runner.unix_sockets import unix_address
from ai_station_runner.video_prepare import driver_supported

router = APIRouter(tags=["experimental live media"])


def session_folder(identity):
    return live_environment.directory(
        get_settings().host_data_dir().resolve(), f"runtime/live-sessions/{UUID(str(identity))}"
    )


def capabilities(mode="face_swap"):
    from ai_station_runner import live_portrait_environment

    policy = live_portrait_environment if mode == "portrait" else live_environment
    root = get_settings().host_data_dir().resolve()
    hardware = collect(root)
    eligible = [int(g["index"]) for g in compatible_gpus(hardware)]
    result = {
        "available": False,
        "experimental": True,
        "ram_mib": RAM_MIB,
        "eligible_gpu_indices": eligible,
        "gpus_per_medium": 1,
        "sample_rate": 22050,
        "block_samples": 4410,
        "maximum_seconds": 3600,
        "reason": "Prepare the Live face and voice runtime first",
    }
    try:
        private = read_json(root / f"runtime/{policy.NAMESPACE}/active.json")
        selected = policy.resolve(root, private)
        result["managed_runtime"] = policy.public_observation(selected["observation"])
        if not policy.QUALIFIED:
            result["reason"] = "Live session transport and recovery are still being qualified"
        elif (
            not eligible
            or (hardware.get("memory") or {}).get("total_mib", 0) < 16384
            or not available()
            or not driver_supported(policy.recipe()["driver_minimum"])
        ):
            result["reason"] = "Live needs compatible CUDA GPUs, 16 GiB host RAM and a user memory scope"
        else:
            result.update(available=True, reason=None)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


def start(manager, body):
    identity = str(body.run_id)
    request = body.model_dump(mode="json")
    if "mode" not in body.model_fields_set:
        request.pop("mode")
    request["permissions"] = sorted(request["permissions"])
    digest = live_environment.fingerprint(request)
    with runtime_install.locked():
        folder = session_folder(identity)
        path = folder / "request.json"
        if path.exists():
            old = read_json(path)
            if old.get("cancellation_requested") or old.get("request_hash") != digest:
                raise HTTPException(409, "The live session was stopped or its immutable request changed")
            try:
                result = manager.inspect(identity)
            except ProcessNotOwned as exc:
                raise HTTPException(409, "Inspect the original live session; do not restart capture") from exc
            if result.get("executor") != NAME:
                raise HTTPException(409, "This process belongs to a different executor")
            return result
        ready = capabilities(mode=body.mode) if body.mode == "portrait" else capabilities()
        if not ready["available"] or body.managed_runtime.model_dump() != ready.get("managed_runtime"):
            raise HTTPException(409, ready.get("reason") or "The Live runtime identity changed")
        if any(g not in ready["eligible_gpu_indices"] for g in body.gpus):
            raise HTTPException(422, "Allocate compatible discovered GPUs for every live medium")
        if not 0 < body.deadline_at - time.time() <= 3600:
            raise HTTPException(422, "Choose a Live deadline within one hour")
        # Persist the dispatch intent before starting. A lost reply never creates
        # another capture process and a pre-dispatch Stop fences a delayed call.
        runtime_install.atomic_json(
            folder,
            path.name,
            {
                "data_root": str(get_settings().host_data_dir().resolve()),
                "request": request,
                "request_hash": digest,
                "stream_secret": secrets.token_hex(32),
                "cancellation_requested": False,
            },
        )
        return manager.start(
            run_id=identity,
            executor=NAME,
            argv=[
                *scope_prefix(identity, RAM_MIB),
                sys.executable,
                "-m",
                "ai_station_runner.live_job",
                str(path),
            ],
            cwd=get_settings().host_data_dir().resolve(),
            deadline_at=body.deadline_at,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "PYTHONUNBUFFERED": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                **scope_environment(),
            },
        )


def cancel(manager, identity):
    identity = str(UUID(str(identity)))
    with runtime_install.locked():
        folder = session_folder(identity)
        path = folder / "request.json"
        saved = read_json(path) if path.exists() else {}
        try:
            info = manager.inspect(identity)
        except ProcessNotOwned:
            info = None
        if info is not None and info.get("executor") != NAME:
            raise HTTPException(409, "This process belongs to a different executor")
        runtime_install.atomic_json(folder, path.name, {**saved, "cancellation_requested": True})
        return (
            manager.cancel(identity)
            if info is not None
            else {"run_id": identity, "executor": NAME, "alive": False, "status": "canceled"}
        )


@router.get("/v1/live/capabilities")
def capabilities_endpoint(mode: Literal["face_swap", "portrait"] = "face_swap"):
    return capabilities(mode=mode) if mode == "portrait" else capabilities()


@router.post("/v1/runs/live")
def start_endpoint(body: LiveRequest):
    return {**start(runtime_install.process_manager(), body), "runner_id": get_settings().runner_id}


@router.post("/v1/live/{identity}/cancel")
def cancel_endpoint(identity: UUID):
    return cancel(runtime_install.process_manager(), identity)


@router.websocket("/v1/live/{identity}/stream")
async def stream(websocket: WebSocket, identity: UUID):
    writer = None
    try:
        from starlette.concurrency import run_in_threadpool

        info = await run_in_threadpool(runtime_install.process_manager().inspect, str(identity))
        if not info.get("alive") or info.get("executor") != NAME:
            await websocket.close(code=4409)
            return
        folder = session_folder(identity)
        saved = read_json(folder / "request.json")
        if saved.get("cancellation_requested"):
            await websocket.close(code=4409)
            return
        with unix_address(folder / "stream.sock") as address:
            reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(address), 2)
        await write_async(writer, saved["stream_secret"].encode())
        acknowledgement = await asyncio.wait_for(read_async(reader), 2)
        if json.loads(acknowledgement).get("ready") is not True:
            raise ValueError("Live broker did not admit the stream")
        await websocket.accept()

        async def upload():
            while True:
                raw = await websocket.receive_bytes()
                decode(raw, incoming=True)
                await write_async(writer, raw)

        async def download():
            while True:
                raw = await read_async(reader)
                if raw.startswith(b"{"):
                    if len(raw) > 4096:
                        raise ValueError("Live observation exceeded its bound")
                    await asyncio.wait_for(websocket.send_text(raw.decode()), 2)
                else:
                    decode(raw, incoming=False)
                    await asyncio.wait_for(websocket.send_bytes(raw), 2)

        async with asyncio.TaskGroup() as group:
            jobs = [group.create_task(upload()), group.create_task(download())]
            await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for job in jobs:
                job.cancel()
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
