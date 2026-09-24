"""Control-plane HTTP API. Execution belongs to the worker."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.chat import router as chat_router
from app.config import get_settings
from app.db import migrate, session_factory, session_scope, utcnow
from app.events import event_dict, list_events
from app.images import MAX_UPLOAD
from app.images import router as image_router
from app.models import Artifact, Run, Setting, WorkerRow
from app.projects import router as project_router
from app.redact import redact_obj
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, request_cancel, run_dict
from app.serialize import artifact_dict
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
    if request.url.path == "/api/images/uploads" and request.method == "POST":
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            return JSONResponse({"detail": "A Content-Length is required for uploads"}, status_code=411)
        if int(length) > MAX_UPLOAD + 64 * 1024:
            return JSONResponse({"detail": "Images must be at most 20 MiB"}, status_code=413)
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
    capability: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    statement = select(Run).order_by(Run.created_at.desc(), Run.id).limit(limit).offset(offset)
    if status:
        statement = statement.where(Run.status == status)
    if capability:
        statement = statement.where(Run.capability == capability)
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
            # Never retain a database transaction while waiting on an SSE client.
            with session_factory()() as current:
                rows = [event_dict(row) for row in list_events(current, str(run_id), cursor)]
                run = current.get(Run, str(run_id))
                terminal = run is None or run.status in TERMINAL
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


@app.get("/api/artifacts")
def artifacts(session: DB, run_id: UUID | None = None, limit: int = Query(100, ge=1, le=500)):
    statement = select(Artifact).order_by(Artifact.created_at.desc()).limit(limit)
    if run_id:
        statement = statement.where(Artifact.run_id == str(run_id))
    return [artifact_dict(row) for row in session.scalars(statement)]


app.include_router(image_router)
app.include_router(chat_router)
app.include_router(project_router)

dist = get_settings().frontend_dist
if dist and Path(dist).is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
