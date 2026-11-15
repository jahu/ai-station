"""Private live-session intent/history and authenticated bounded duplex transport."""

import asyncio
import contextlib
import secrets
from datetime import timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import accounts
from app.config import get_settings
from app.data_access import data_session_for
from app.db import control_session_factory, session_scope, utcnow
from app.live_executor import NAME, RAM_MIB
from app.models import Artifact, Run, Task
from app.paths import safe_join
from app.private_access import access_origins, valid_host, valid_origin
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, run_dict

router = APIRouter(prefix="/api/live", tags=["experimental live sessions"])
DB = Annotated[Session, Depends(session_scope, scope="function")]
INTENT = "live.identity"


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    mode: Literal["face_swap", "portrait"] = "face_swap"
    image_artifact_id: UUID | None = None
    voice_artifact_id: UUID | None = None
    maximum_seconds: StrictInt = Field(default=1800, ge=60, le=3600)

    @model_validator(mode="after")
    def medium(self):
        if self.mode == "portrait" and self.image_artifact_id is None:
            raise ValueError("Animated portrait needs a reference image")
        if self.image_artifact_id is None and self.voice_artifact_id is None:
            raise ValueError("Choose a portrait, a reference voice, or both")
        return self


def reference(session, identity, medium, owner):
    source = session.get(Artifact, str(identity))
    allowed = (
        {"image/png", "image/jpeg"}
        if medium == "image"
        else {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/flac", "audio/x-flac"}
    )
    if (
        source is None
        or source.owner_id != owner
        or source.mime_type not in allowed
        or source.trashed_at
        or source.purged_at
        or source.purge_run_id
        or not 1 <= source.size_bytes <= 20 * 1024**2
    ):
        raise ValueError("Choose an available owned portrait or clear WAV, MP3 or FLAC recording")
    path = safe_join(get_settings().data_dir, source.relative_path)
    if (
        not source.relative_path.startswith(("artifacts/", "uploads/"))
        or path.stat().st_size != source.size_bytes
    ):
        raise ValueError("The live reference changed or is unavailable")
    return {k: getattr(source, k) for k in ("relative_path", "sha256", "size_bytes")}


def private_run(session, identity):
    run = session.get(Run, str(identity))
    if run is None or run.executor_type != NAME:
        raise HTTPException(404, "Live session was not found")
    return run


def view(run):
    return {
        "run": run_dict(run),
        "ready": run.status == "running" and run.metadata_json.get("live_ready") is True,
    }


@router.get("/capabilities")
def capabilities(session: DB, mode: Literal["face_swap", "portrait"] = "face_swap"):
    scope = getattr(session, "scope", None)
    try:
        ready = RunnerClient().request(
            "GET", "/v1/live/capabilities" + ("?mode=portrait" if mode == "portrait" else "")
        )
    except (RunnerError, RunnerUnavailable):
        ready = {"available": False, "reason": "Connect the Host Runner to prepare Live"}
    if scope is None or scope.inspect_all:
        ready = {
            **ready,
            "available": False,
            "reason": "Sign in to your own account to use camera and microphone",
        }
    secure = next((v for v in sorted(access_origins()) if v.startswith("https://")), None)
    return {
        **ready,
        "can_prepare": bool(scope and scope.administrator and not scope.read_only),
        "secure_origin": secure,
    }


@router.post("/sessions", status_code=202)
def start(body: Start, session: DB):
    scope = getattr(session, "scope", None)
    if scope is None or scope.read_only:
        raise HTTPException(403, "Sign in to your own account to start Live")
    identity = str(body.client_request_id)
    request = body.model_dump(mode="json")
    if "mode" not in body.model_fields_set:
        request.pop("mode")
    previous = session.get(Task, identity)
    if previous is not None:
        if previous.intent != INTENT or previous.metadata_json.get("live_request") != request:
            raise HTTPException(409, "The live session identity belongs to a different request")
        return view(session.scalar(select(Run).where(Run.task_id == identity, Run.executor_type == NAME)))
    ready = capabilities(session, mode=body.mode)
    if not ready.get("available"):
        raise HTTPException(409, ready.get("reason") or "Prepare the Live runtime first")
    count = int(body.image_artifact_id is not None) + int(body.voice_artifact_id is not None)
    if len(ready.get("eligible_gpu_indices", [])) < count:
        raise HTTPException(409, "Choose face or voice alone on one GPU; both need two compatible GPUs")
    parameters = {
        "mode": body.mode,
        "managed_runtime": ready["managed_runtime"],
        "eligible_gpu_indices": ready["eligible_gpu_indices"],
        "seed": secrets.randbelow(2**31),
        "execution_deadline_at": (utcnow() + timedelta(seconds=body.maximum_seconds)).isoformat(),
    }
    try:
        for medium, chosen in (("image", body.image_artifact_id), ("voice", body.voice_artifact_id)):
            if chosen is not None:
                parameters[medium + "_artifact_id"] = str(chosen)
                parameters[medium] = reference(session, chosen, medium, scope.user_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    parameters["parent_artifact_ids"] = [
        str(v) for v in (body.image_artifact_id, body.voice_artifact_id) if v is not None
    ]
    task = Task(
        id=identity,
        title="Live · animated portrait"
        if body.mode == "portrait"
        else "Live · face and voice"
        if count == 2
        else "Live · face"
        if body.image_artifact_id
        else "Live · voice",
        prompt="Transform this browser camera/microphone session using the selected fixed references",
        capability=INTENT,
        intent=INTENT,
        status="open",
        metadata_json={"live_request": request},
    )
    try:
        session.add(task)
        session.flush()
        run = create_run(
            session,
            task,
            run_type="live",
            capability=INTENT,
            executor_type=NAME,
            execution_target="host",
            operation_key="live:1",
            parameters=parameters,
            permissions=["filesystem_read", "workspace_write"],
            requested_resources={"ram_mib": RAM_MIB},
            requested_gpu="auto",
            retry_class="inspect",
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.get(Task, identity)
        if existing and existing.intent == INTENT and existing.metadata_json.get("live_request") == request:
            return view(session.scalar(select(Run).where(Run.task_id == identity, Run.executor_type == NAME)))
        raise HTTPException(409, "The live session identity is already in use") from exc
    return view(run)


@router.get("/sessions")
def history(session: DB):
    return [
        view(run)
        for run in session.scalars(
            select(Run).where(Run.executor_type == NAME).order_by(Run.created_at.desc()).limit(20)
        )
    ]


@router.get("/sessions/{identity}")
def inspect(identity: UUID, session: DB):
    return view(private_run(session, identity))


def authorize_stream(websocket, identity, expected=None):
    if not getattr(websocket.app.state, "account_access_enabled", False):
        raise PermissionError("Live requires an account")
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    if (
        not valid_host(host)
        or not valid_origin(origin)
        or urlsplit(origin).netloc != host
        or websocket.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise PermissionError("Live requires an allowed same-origin browser")
    with control_session_factory()() as auth:
        principal = accounts.authenticate_cookies(auth, dict(websocket.cookies))
        auth.commit()
    if principal is None or expected is not None and principal != expected:
        raise PermissionError("The live account session ended")
    with data_session_for(principal) as session:
        run = private_run(session, identity)
        if (
            run.owner_id != principal.user_id
            or run.status != "running"
            or not run.metadata_json.get("live_ready")
        ):
            raise PermissionError("The owned live session is not ready")
        for medium in ("image", "voice"):
            if (
                run.parameters.get(medium) is not None
                and reference(session, run.parameters[medium + "_artifact_id"], medium, principal.user_id)
                != run.parameters[medium]
            ):
                raise PermissionError("A live reference was revoked or changed")
    return principal


@router.websocket("/sessions/{identity}/stream")
async def stream(websocket: WebSocket, identity: UUID):
    try:
        principal = await run_in_threadpool(authorize_stream, websocket, identity)
        from websockets.asyncio.client import unix_connect

        async with unix_connect(
            path=get_settings().runner_socket,
            uri=f"ws://runner/v1/live/{identity}/stream",
            max_size=512 * 1024 + 128,
            max_queue=4,
            compression=None,
            open_timeout=5,
            close_timeout=2,
        ) as native:
            await websocket.accept()

            async def upload():
                while True:
                    message = await websocket.receive()
                    raw = message.get("bytes")
                    if message["type"] == "websocket.disconnect":
                        return
                    if raw is None or not 18 < len(raw) <= 512 * 1024 + 18:
                        raise ValueError("Live accepts bounded binary media only")
                    await asyncio.wait_for(native.send(raw), 2)

            async def download():
                async for message in native:
                    if isinstance(message, bytes):
                        await asyncio.wait_for(websocket.send_bytes(message), 2)
                    else:
                        if len(message) > 4096:
                            raise ValueError("Live observation exceeded its bound")
                        await asyncio.wait_for(websocket.send_text(message), 2)

            async def authorization():
                while True:
                    await asyncio.sleep(1)
                    await run_in_threadpool(authorize_stream, websocket, identity, principal)

            async with asyncio.TaskGroup() as group:
                jobs = [
                    group.create_task(upload()),
                    group.create_task(download()),
                    group.create_task(authorization()),
                ]
                await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                for job in jobs:
                    job.cancel()
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
