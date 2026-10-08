"""Control-plane HTTP API. Execution belongs to the worker."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agents_api import router as agent_router
from app.audio import router as audio_router
from app.avatars import router as avatar_router
from app.chat import router as chat_router
from app.codex_coding import router as codex_router
from app.coding_sessions import router as coding_sessions_router
from app.config import get_settings
from app.cursor_coding import router as cursor_coding_router
from app.dashboard import router as dashboard_router
from app.db import migrate, session_factory, session_scope, utcnow
from app.events import event_dict, list_events
from app.images import MAX_UPLOAD
from app.images import router as image_router
from app.library import router as library_router
from app.llama import router as llama_router
from app.local_coding import router as local_coding_router
from app.memory_api import router as memory_router
from app.model_registry import router as model_router
from app.models import Run, Setting, WorkerRow
from app.project_setup import router as project_setup_router
from app.projects import router as project_router
from app.providers import ProviderError
from app.publication import router as publication_router
from app.redact import redact_obj
from app.reviewed_commits import router as commit_router
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, request_cancel, run_dict
from app.runtime_registry import router as runtime_router
from app.state import TERMINAL, InvalidTransition, RunStatus
from app.telemetry_store import history

DB = Annotated[Session, Depends(session_scope)]


@asynccontextmanager
async def lifespan(_app):
    migrate()
    yield


app = FastAPI(title="AI Station", version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])


@app.middleware("http")
async def local_requests(request: Request, call_next):
    if request.url.path in {"/api/images/uploads", "/api/audio/uploads"} and request.method == "POST":
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            return JSONResponse({"detail": "A Content-Length is required for uploads"}, status_code=411)
        if int(length) > MAX_UPLOAD + 64 * 1024:
            return JSONResponse({"detail": "Uploads must be at most 20 MiB"}, status_code=413)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site writes are not allowed"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(InvalidTransition)
async def invalid_transition(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=409)


@app.exception_handler(ProviderError)
async def provider_unavailable(_request, error):
    return JSONResponse({"detail": redact_obj(str(error))}, status_code=409)


@app.exception_handler(RunnerUnavailable)
async def runner_unavailable(_request, _error):
    return JSONResponse({"detail": "Host Runner is unavailable"}, status_code=503)


@app.exception_handler(RunnerError)
async def runner_error(_request, error):
    return JSONResponse({"detail": redact_obj(error.detail)}, status_code=502)


def get_run(session: Session, run_id: UUID) -> Run:
    run = session.get(Run, str(run_id))
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/api/health")
def health(session: DB):
    session.execute(text("SELECT 1"))
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/runs")
def runs(
    session: DB,
    status: RunStatus | None = None,
    capability: str | None = Query(None, max_length=120),
    executor: str | None = Query(None, max_length=80),
    target: Literal["host", "container", "remote-node"] | None = None,
    project_id: UUID | None = None,
    agent_id: UUID | None = None,
    gpu: str | None = Query(None, max_length=200),
    created_after: AwareDatetime | None = None,
    created_before: AwareDatetime | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if created_after and created_before and created_after > created_before:
        raise HTTPException(422, "Created-after must not be later than created-before")
    statement = select(Run).order_by(Run.created_at.desc(), Run.id).limit(limit).offset(offset)
    if status:
        statement = statement.where(Run.status == status)
    if capability:
        statement = statement.where(Run.capability == capability)
    for column, value in (
        (Run.executor_type, executor),
        (Run.execution_target, target),
        (Run.project_id, str(project_id) if project_id else None),
        (Run.agent_id, str(agent_id) if agent_id else None),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if gpu is not None:
        statement = statement.where(
            or_(Run.actual_gpu == gpu, (Run.actual_gpu.is_(None)) & (Run.requested_gpu == gpu))
        )
    if created_after:
        statement = statement.where(Run.created_at >= created_after)
    if created_before:
        statement = statement.where(Run.created_at <= created_before)
    return [redact_obj(run_dict(run)) for run in session.scalars(statement)]


@app.get("/api/runs/{run_id}")
def run_detail(run_id: UUID, session: DB):
    return redact_obj(run_dict(get_run(session, run_id)))


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: UUID, session: DB):
    run = request_cancel(session, get_run(session, run_id))
    session.commit()
    return redact_obj(run_dict(run))


@app.get("/api/runs/{run_id}/events")
def events(run_id: UUID, session: DB, after: int = Query(0, ge=0)):
    get_run(session, run_id)
    return [event_dict(event) for event in list_events(session, str(run_id), after)]


def read_event_batch(run_id: str, cursor: int):
    # The thread owns and closes its session before yielding anything to SSE.
    with session_factory()() as current:
        rows = [event_dict(row) for row in list_events(current, run_id, cursor)]
        run = current.get(Run, run_id)
        return rows, run is None or run.status in TERMINAL


@app.get("/api/runs/{run_id}/stream")
def stream(
    run_id: UUID,
    session: DB,
    after: int = Query(0, ge=0),
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
):
    get_run(session, run_id)
    session.rollback()

    async def replay():
        cursor = max(after, last_event_id or 0)
        while True:
            # SQLite may wait on another request's writer reservation. Keep that
            # wait off the HTTP event loop so response/dependency cleanup can run.
            rows, terminal = await asyncio.to_thread(read_event_batch, str(run_id), cursor)
            for row in rows:
                cursor = row["sequence"]
                yield f"id: {cursor}\ndata: {json.dumps(row)}\n\n"
            if terminal:
                yield "event: end\ndata: {}\n\n"
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        replay(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class TestRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Execution self-test", min_length=1, max_length=300)


@app.post("/api/testing/runs", status_code=202)
def enqueue_test(body: TestRunBody, session: DB):
    if not get_settings().enable_test_executor:
        raise HTTPException(404, "Test executor is disabled")
    task = create_task(session, title=body.title, prompt="", capability="system.self_test")
    run = create_run(
        session,
        task,
        run_type="test",
        capability="system.self_test",
        executor_type="fake",
        execution_target="container",
        retry_class="safe",
    )
    session.commit()
    return run_dict(run)


@app.get("/api/system/hardware")
def hardware():
    return RunnerClient(timeout=8).hardware()


@app.get("/api/system/status")
def system_status(session: DB):
    counts = dict(session.execute(select(Run.status, func.count()).group_by(Run.status)).all())
    cutoff = utcnow() - timedelta(seconds=get_settings().lease_seconds)
    workers = session.scalars(select(WorkerRow).order_by(WorkerRow.last_heartbeat.desc()).limit(50))
    scheduler = session.get(Setting, "scheduler_heartbeat")
    heartbeat = scheduler.value.get("at") if scheduler else None
    return {
        "counts": counts,
        "workers": [
            {
                "id": row.id,
                "available": row.last_heartbeat >= cutoff,
                "last_heartbeat": row.last_heartbeat.isoformat(),
            }
            for row in workers
        ],
        "scheduler": {
            "available": bool(heartbeat and heartbeat >= cutoff.isoformat()),
            "last_heartbeat": heartbeat,
        },
    }


@app.get("/api/system/diagnostics")
def diagnostics():
    return RunnerClient(timeout=90).diagnostics()


@app.get("/api/system/history")
def telemetry_history(session: DB, limit: int = Query(240, ge=1, le=2000)):
    return history(session, limit)


app.include_router(cursor_coding_router)
app.include_router(local_coding_router)
app.include_router(dashboard_router)
app.include_router(image_router)
app.include_router(chat_router)
app.include_router(audio_router)
app.include_router(avatar_router)
app.include_router(commit_router)
app.include_router(codex_router)
app.include_router(coding_sessions_router)
app.include_router(publication_router)
app.include_router(library_router)
app.include_router(project_setup_router)
app.include_router(project_router)
app.include_router(memory_router)
app.include_router(model_router)
app.include_router(agent_router)
app.include_router(runtime_router)
app.include_router(llama_router)

dist = get_settings().frontend_dist
if dist and Path(dist).is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
