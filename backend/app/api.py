"""Control-plane HTTP API. Execution belongs to the worker."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent_documents import router as document_router
from app.agent_drafts import router as agent_draft_router
from app.agents_api import router as agent_router
from app.approvals import resolve_run_approval, run_public
from app.artifact_purge import router as artifact_purge_router
from app.audio import router as audio_router
from app.avatars import router as avatar_router
from app.browser import router as browser_router
from app.chat import router as chat_router
from app.chat_providers import router as chat_provider_router
from app.chat_reasoning import router as chat_reasoning_router
from app.codex_coding import router as codex_router
from app.coding_sessions import router as coding_sessions_router
from app.config import get_settings
from app.connectors import router as connector_router
from app.cursor_coding import router as cursor_coding_router
from app.dashboard import router as dashboard_router
from app.data_inputs import router as data_inputs_router
from app.db import control_session_factory, get_engine, migrate, session_factory, session_scope, utcnow
from app.email_delivery import router as email_router
from app.embeddings import router as embedding_router
from app.events import event_dict, list_events
from app.images import MAX_UPLOAD
from app.images import router as image_router
from app.library import router as library_router
from app.llama import router as llama_router
from app.local_coding import router as local_coding_router
from app.maintenance import router as maintenance_router
from app.market_feeds import router as market_feed_router
from app.media_jobs import router as media_jobs_router
from app.media_translation import router as generation_router
from app.memory_api import router as memory_router
from app.model_definitions import router as model_definition_router
from app.model_registry import router as model_router
from app.models import Run, Setting, WorkerRow
from app.music import router as music_router
from app.nodes import router as nodes_router
from app.notices import router as notice_router
from app.operator_auth import refresh_operator_cookie, refuse_non_loopback_bind, require_operator_session
from app.operator_auth import router as operator_auth_router
from app.private_access import valid_host, valid_origin
from app.private_ui import router as private_ui_router
from app.project_setup import router as project_setup_router
from app.projects import router as project_router
from app.providers import ProviderError
from app.publication import router as publication_router
from app.recovery import lease_health
from app.redact import redact_obj
from app.reviewed_commits import router as commit_router
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, request_cancel, run_dict
from app.runtime_registry import router as runtime_router
from app.site_preview import router as site_preview_router
from app.skills import router as skill_router
from app.state import TERMINAL, InvalidTransition, RunStatus
from app.telemetry_store import history
from app.transcription import router as transcription_router
from app.video import router as video_router

DB = Annotated[Session, Depends(session_scope)]


@asynccontextmanager
async def lifespan(_app):
    migrate()
    with control_session_factory()() as session:
        accounts_active = getattr(_app.state, "account_access_enabled", False)
        refuse_non_loopback_bind(session, accounts_active=accounts_active)
        if accounts_active:
            from app.bootstrap_setup import ensure_setup_proof

            ensure_setup_proof(session)
    yield


app = FastAPI(title="AI Station", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def local_requests(request: Request, call_next):
    if not await run_in_threadpool(valid_host, request.headers.get("host", "")):
        return JSONResponse({"detail": "Invalid host header"}, status_code=400)
    if (
        request.url.path
        in {
            "/api/images/uploads",
            "/api/audio/uploads",
            "/api/audio/transcription/uploads",
            "/api/data/uploads",
            "/api/documents/uploads",
        }
        and request.method == "POST"
    ):
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            return JSONResponse({"detail": "A Content-Length is required for uploads"}, status_code=411)
        if int(length) > MAX_UPLOAD + 64 * 1024:
            return JSONResponse({"detail": "Uploads must be at most 20 MiB"}, status_code=413)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and not await run_in_threadpool(valid_origin, origin):
            return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site writes are not allowed"}, status_code=403)
    # SQLite may wait on another writer. Keep that wait off the event loop
    # so in-flight responses can finish and release their database sessions.
    accounts_active = getattr(request.app.state, "account_access_enabled", False)
    if accounts_active:
        from app.account_http import require_account_session

        guard = require_account_session
    else:
        guard = require_operator_session
    gated = await run_in_threadpool(guard, request)
    if gated is not None:
        return gated
    if accounts_active:
        from app.account_http import inspection_requested, refresh_account_cookie
        from app.data_access import DataScope
        from app.data_context import bind_data_scope

        try:
            inspect_all = inspection_requested(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        principal = request.state.account_principal
        scope = (
            DataScope(
                principal.user_id,
                inspect_all,
                administrator=principal.is_admin,
                session_id=principal.session_id,
            )
            if principal
            else None
        )
        with bind_data_scope(scope):
            response = await call_next(request)
        await run_in_threadpool(refresh_account_cookie, request, response)
    else:
        response = await call_next(request)
        await run_in_threadpool(refresh_operator_cookie, request, response)
    # The entry document selects versioned bundles; caching it can retain an old UI after deployment.
    if request.url.path.startswith("/api/operator-auth") or request.url.path in {"/", "/index.html"}:
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, error):
    # Model-level errors can contain the complete submitted form, including a
    # write-only password. Keep actionable diagnostics, never input or context.
    return JSONResponse(
        {"detail": [{key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()]},
        status_code=422,
    )


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
def health():
    # Public readiness checks reveal no account rows or application history.
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
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
    return redact_obj(run_public(session, get_run(session, run_id)))


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Literal["granted", "denied"]


@app.post("/api/runs/{run_id}/approval")
def decide_approval(run_id: UUID, body: ApprovalDecision, session: DB):
    try:
        run = resolve_run_approval(session, get_run(session, run_id), body.resolution)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return redact_obj(run_public(session, run))


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: UUID, session: DB):
    run = request_cancel(session, get_run(session, run_id))
    session.commit()
    return redact_obj(run_public(session, run))


@app.post("/api/runs/{run_id}/retry-workflow", status_code=202)
def retry_workflow_run(run_id: UUID, session: DB):
    from app.schedule import retry_workflow

    try:
        created = retry_workflow(session, get_run(session, run_id))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return redact_obj(run_public(session, session.get(Run, created)))


@app.get("/api/runs/{run_id}/events")
def events(run_id: UUID, session: DB, after: int = Query(0, ge=0)):
    get_run(session, run_id)
    return [event_dict(event) for event in list_events(session, str(run_id), after)]


def read_event_batch(run_id: str, cursor: int):
    from app.accounts import Principal, _actor
    from app.data_access import DataScope
    from app.data_context import current_data_scope

    scope = current_data_scope()
    # Authority and events share one transaction: revocation cannot slip into
    # a gap between checking a device and reading the next private event batch.
    with session_factory()() as current:
        if isinstance(scope, DataScope) and scope.session_id:
            _actor(
                current,
                Principal(scope.user_id, scope.session_id, scope.administrator),
                admin=scope.inspect_all,
                lock=True,
            )
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
        from app.accounts import AccountError

        cursor = max(after, last_event_id or 0)
        while True:
            # SQLite may wait on another request's writer reservation. Keep that
            # wait off the HTTP event loop so response/dependency cleanup can run.
            try:
                rows, terminal = await asyncio.to_thread(read_event_batch, str(run_id), cursor)
            except AccountError:
                yield 'event: end\ndata: {"authentication_required": true}\n\n'
                return
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


@app.get("/api/system/gpu-processes")
def gpu_process_observation():
    from app.gpu_processes import normalize

    try:
        return normalize(RunnerClient(timeout=4).gpu_processes())
    except (RunnerError, RunnerUnavailable):
        return normalize(None)


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
        **lease_health(session),
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
app.include_router(chat_reasoning_router)
app.include_router(chat_provider_router)
app.include_router(connector_router)

app.include_router(email_router)
app.include_router(market_feed_router)
app.include_router(audio_router)
app.include_router(music_router)
app.include_router(transcription_router)
app.include_router(avatar_router)
app.include_router(video_router)
app.include_router(media_jobs_router)
app.include_router(commit_router)
app.include_router(codex_router)
app.include_router(coding_sessions_router)
app.include_router(publication_router)
app.include_router(library_router)
app.include_router(artifact_purge_router)
app.include_router(generation_router)
app.include_router(project_setup_router)
app.include_router(data_inputs_router)
app.include_router(project_router)
app.include_router(maintenance_router)
app.include_router(memory_router)
app.include_router(embedding_router)
app.include_router(private_ui_router)
app.include_router(operator_auth_router)
app.include_router(nodes_router)
app.include_router(model_definition_router)
app.include_router(model_router)
app.include_router(document_router)
app.include_router(agent_router)
app.include_router(agent_draft_router)
app.include_router(notice_router)
app.include_router(skill_router)
app.include_router(runtime_router)
app.include_router(llama_router)
app.include_router(browser_router)
app.include_router(site_preview_router)

dist = get_settings().frontend_dist
if dist and Path(dist).is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
