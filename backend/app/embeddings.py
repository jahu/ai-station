"""Managed CPU semantic memory, with advanced compatible local endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.config import get_settings
from app.db import session_scope, utcnow
from app.embedding_models import (
    DIMENSION,
    MODEL_ID,
    dependencies_available,
    descriptor,
    installation,
    storage,
)
from app.embedding_process import CpuEmbeddingProcess, EmbeddingStopped, check_running
from app.events import append_event
from app.local_provider import validate_endpoint
from app.models import MemoryEmbedding, MemoryEntry, Run, Setting
from app.paths import PathBoundaryError
from app.providers import ProviderError
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.secrets import authorization_headers, parse_secret_ref, public_secret
from app.serialize import memory_dict
from app.state import ACTIVE, RunStatus

router = APIRouter(prefix="/api/memory/embeddings", tags=["memory"])
DB = Annotated[Session, Depends(session_scope)]
SETUP_KEY = "memory_embeddings"
SETUP_FIELDS = (
    "backend",
    "revision",
    "model_id",
    "prepare_run_id",
    "endpoint",
    "model",
    "secret_ref",
    "last_health_run_id",
    "last_index_run_id",
    "dimension",
)
PROBE_TEXT = "ai-station embedding probe"
MAX_INPUT = 8000
INDEX_BATCH = 50
ACTIVITY_KEY = "memory_embedding_activity"
ACTIVITY_IDS = ("prepare_run_id", "last_health_run_id", "last_index_run_id")
CONFIG_FIELDS = ("backend", "revision", "model_id", "endpoint", "model", "secret_ref")


def _configuration(value):
    return {
        "backend": value.get("backend") or "endpoint",
        "revision": value.get("revision") or 0,
        "model_id": value.get("model_id"),
        "endpoint": value.get("endpoint") or "",
        "model": value.get("model") or "",
        "secret_ref": value.get("secret_ref") or "",
    }


SEARCH_LIMIT = 30
MIN_DIM = 8
MAX_DIM = 4096


class SetupBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    endpoint: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    secret_ref: str = Field(default="", max_length=200)
    clear: StrictBool = False
    expected_revision: int | None = Field(default=None, ge=0, strict=True)


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=2000)
    scope: Literal["global", "agent", "project", "conversation"] | None = None
    scope_id: UUID | None = None

    @model_validator(mode="after")
    def valid_scope(self):
        if self.scope_id is not None and self.scope in {None, "global"}:
            raise ValueError("Choose a target scope for a scoped semantic search")
        return self


class PrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: Literal[MODEL_ID] = MODEL_ID
    expected_revision: int = Field(ge=0, strict=True)
    confirm_download: StrictBool = False


def vector_identity(value):
    identity = {key: value.get(key) for key in ("backend", "endpoint", "model", "model_id")}
    identity["backend"] = identity["backend"] or "endpoint"
    identity["encoding"] = "e5-prefix-chunks-v1" if identity["backend"] == "local_cpu" else "compatible-v1"
    return "embedding:" + content_hash(json.dumps(identity, sort_keys=True))


def validate_binding(session, run):
    current = load_setup(session)
    frozen = run.parameters
    if frozen.get("revision") is not None:
        if current["revision"] != frozen["revision"] or vector_identity(current) != frozen.get(
            "embedding_identity"
        ):
            raise ValueError("Semantic memory settings changed; start a new Run")
    elif (current["endpoint"], current["model"]) != (frozen.get("endpoint"), frozen.get("model")):
        raise ValueError("Semantic memory settings changed; start a new Run")
    return current


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def validate_vector(raw) -> list[float]:
    if not isinstance(raw, list) or not MIN_DIM <= len(raw) <= MAX_DIM:
        raise ValueError("Embedding vector is missing or has an unsupported size")
    values = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise ValueError("Embedding vector contains a non-numeric component")
        value = float(item)
        if not math.isfinite(value):
            raise ValueError("Embedding vector contains a non-finite component")
        values.append(value)
    if all(item == 0 for item in values):
        raise ValueError("Refusing an all-zero embedding vector")
    return values


def cosine(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right):
        return None
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0 or norm_right == 0:
        return None
    return dot / (norm_left * norm_right)


def load_setup(session) -> dict:
    from app.data_access import ScopedSession
    from app.personal_settings import preference_row

    if isinstance(session, ScopedSession):
        # This one fixed model-service setting is machine configuration. Read
        # its value internally, without granting access to the Settings table
        # or attaching a mutable administrative record to the user's session.
        session.scope
        stored = session.connection().scalar(select(Setting.value).where(Setting.key == SETUP_KEY))
    else:
        row = session.get(Setting, SETUP_KEY)
        stored = row.value if row else None
    value = dict(stored) if isinstance(stored, dict) else {}
    result = {
        "backend": value.get("backend") or "endpoint",
        "revision": value.get("revision") or 0,
        "model_id": value.get("model_id"),
        "prepare_run_id": value.get("prepare_run_id"),
        "endpoint": value.get("endpoint") or "",
        "model": value.get("model") or "",
        "secret_ref": value.get("secret_ref") or "",
        "last_health_run_id": value.get("last_health_run_id"),
        "last_index_run_id": value.get("last_index_run_id"),
        "dimension": value.get("dimension"),
        "configured": bool(
            value.get("model")
            and (
                value.get("endpoint")
                or value.get("backend") == "local_cpu"
                and value.get("model_id") == MODEL_ID
            )
        ),
    }
    if isinstance(session, ScopedSession):
        row = preference_row(session, ACTIVITY_KEY)
        activity = row.value if row and isinstance(row.value, dict) else {}
        if activity.get("revision") == result["revision"] and activity.get("identity") == vector_identity(
            result
        ):
            result.update({key: activity.get(key) for key in (*ACTIVITY_IDS, "dimension")})
        for key in ACTIVITY_IDS:
            if result.get(key) and session.get(Run, result[key]) is None:
                result[key] = None
    return result


def _save_activity(session, payload):
    from app.data_access import DataAccessError
    from app.personal_settings import preference_row

    for key in ACTIVITY_IDS:
        if payload.get(key):
            run = session.get(Run, payload[key])
            if run is None or run.owner_id != session.scope.user_id:
                raise DataAccessError("Embedding activity must belong to the executing account")
    row = preference_row(session, ACTIVITY_KEY, default={}, lock=True)
    config = _configuration(payload)
    row.value = {
        "revision": config["revision"],
        "identity": vector_identity(config),
        **{key: payload.get(key) for key in (*ACTIVITY_IDS, "dimension")},
    }
    session.flush()


def save_setup(session, payload: dict) -> dict:
    from app.data_access import DataAccessError, ScopedSession

    if isinstance(session, ScopedSession):
        if _configuration(payload) != _configuration(load_setup(session)):
            if not session.scope.administrator or session.scope.execution or session.scope.read_only:
                raise DataAccessError("Embedding model configuration requires an administrator request")
            row = session.get(Setting, SETUP_KEY)
            if row is None:
                row = Setting(key=SETUP_KEY, value={})
                session.add(row)
            # Shared configuration contains model service metadata only. Run
            # identities and learned per-account dimensions stay private.
            row.value = {**_configuration(payload), "dimension": payload.get("dimension")}
        _save_activity(session, payload)
        return load_setup(session)
    row = session.get(Setting, SETUP_KEY)
    if row is None:
        row = Setting(key=SETUP_KEY, value={})
        session.add(row)
    row.value = {key: payload.get(key) for key in SETUP_FIELDS}
    session.flush()
    return load_setup(session)


def _activate_prepared_model(session, run, payload):
    from sqlalchemy.orm import object_session

    from app.data_access import DataAccessError, ScopedSession
    from app.models import User

    if not isinstance(session, ScopedSession):
        return save_setup(session, payload)
    scope = session.scope
    user = session.get(User, scope.user_id, populate_existing=True)
    session.refresh(run)
    if (
        not scope.execution
        or scope.read_only
        or object_session(run) is not session
        or run.owner_id != scope.user_id
        or run.executor_type != "memory_embed"
        or run.capability != "memory.embed.prepare"
        or run.status != "running"
        or user is None
        or not user.enabled
        or not user.is_admin
        or user.bootstrap_pending
        or run.parameters.get("requested_model_id") != MODEL_ID
    ):
        raise DataAccessError("Only an authorized owned preparation Run can activate an embedding model")
    stored = session.connection().scalar(
        select(Setting.value).where(Setting.key == SETUP_KEY).with_for_update()
    )
    current = _configuration(stored if isinstance(stored, dict) else {})
    expected = {
        "backend": "local_cpu",
        "revision": current["revision"] + 1,
        "model_id": MODEL_ID,
        "endpoint": "",
        "model": MODEL_ID,
        "secret_ref": "",
    }
    if (
        current["revision"] != run.parameters["revision"]
        or vector_identity(current) != run.parameters["embedding_identity"]
        or _configuration(payload) != expected
        or payload.get("dimension") != DIMENSION
    ):
        raise DataAccessError("The verified preparation no longer matches the shared model configuration")
    # One fixed, role/owner/revision-checked infrastructure write; the execution
    # session never acquires arbitrary access to machine settings.
    values = {**expected, "dimension": DIMENSION}
    table = Setting.__table__
    connection = session.connection()
    if stored is None:
        connection.execute(table.insert().values(key=SETUP_KEY, value=values))
    else:
        connection.execute(table.update().where(table.c.key == SETUP_KEY).values(value=values))
    _save_activity(session, payload)
    return load_setup(session)


def require_setup(session) -> dict:
    setup = load_setup(session)
    if not setup["configured"]:
        raise HTTPException(
            409,
            "Set up the local CPU embedding model or choose a compatible local endpoint first.",
        )
    return setup


def setup_view(session, setup=None):
    from app.data_access import ScopedSession

    setup = setup or load_setup(session)
    pairs = session.execute(
        select(MemoryEmbedding, MemoryEntry)
        .join(MemoryEntry)
        .where(MemoryEmbedding.model == vector_identity(setup), MemoryEntry.enabled.is_(True))
    )
    indexed = sum(1 for vector, entry in pairs if vector.content_hash == content_hash(entry.content))
    memories = (
        session.scalar(select(func.count()).select_from(MemoryEntry).where(MemoryEntry.enabled.is_(True)))
        or 0
    )
    local = installation(get_settings().data_dir)

    def operation(key):
        run = session.get(Run, setup[key]) if setup.get(key) else None
        return run_dict(run) if run else None

    health_run, index_run = operation("last_health_run_id"), operation("last_index_run_id")
    credentials = public_secret(setup["secret_ref"])
    if isinstance(session, ScopedSession):
        # Shared model readiness never reveals the administrator's configured
        # secret reference or another account's private health/index Run IDs.
        credentials = {
            **credentials,
            "secret_ref": "",
            "secret_source": "station" if setup["secret_ref"] else "none",
        }

    return {
        **{
            key: setup[key]
            for key in ("backend", "revision", "endpoint", "model", "model_id", "configured", "dimension")
        },
        **credentials,
        "last_health_run_id": health_run["id"] if health_run else None,
        "last_index_run_id": index_run["id"] if index_run else None,
        "indexed_count": indexed,
        "memory_count": memories,
        "can_prepare": not isinstance(session, ScopedSession)
        or bool(session.scope.administrator and not session.scope.execution and not session.scope.read_only),
        "local_model": {
            **descriptor(),
            "storage": storage(get_settings().data_dir),
            "available": dependencies_available(),
            "installed": local["installed"],
            "reason": local["reason"],
        },
        "prepare_run": operation("prepare_run_id"),
        "index_run": index_run,
        "health_run": health_run,
    }


@router.get("/setup")
def get_setup(session: DB):
    return setup_view(session)


@router.put("/setup")
def put_setup(body: SetupBody, session: DB):
    current = load_setup(session)
    if body.expected_revision is not None and body.expected_revision != current["revision"]:
        raise HTTPException(409, "Memory settings changed. Reload before saving.")
    if body.clear:
        save_setup(session, {"revision": current["revision"] + 1})
        session.commit()
        return setup_view(session)
    current = load_setup(session)
    try:
        parse_secret_ref(body.secret_ref)
        endpoint = validate_endpoint(body.endpoint, "local")
    except (ValueError, PathBoundaryError, ProviderError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if not body.model:
        raise HTTPException(422, "Select the embeddings model name the local endpoint already serves")
    if endpoint.endswith("/embeddings") or endpoint.endswith("/embeddings/"):
        raise HTTPException(422, "Save the OpenAI-compatible /v1 base URL, not the /embeddings path")
    same = endpoint == current["endpoint"] and body.model == current["model"]
    saved = save_setup(
        session,
        {
            "backend": "endpoint",
            "revision": current["revision"] + 1,
            "endpoint": endpoint,
            "model": body.model,
            "secret_ref": body.secret_ref,
            "last_health_run_id": current["last_health_run_id"] if same else None,
            "last_index_run_id": current["last_index_run_id"] if same else None,
            "dimension": current["dimension"] if same else None,
        },
    )
    session.commit()
    return setup_view(session, saved)


def _enqueue(session, *, capability, title, extra, setup, task=None, parent=None):
    from app.data_access import ScopedSession

    busy = (
        select(Run.id)
        .where(
            Run.executor_type == "memory_embed",
            Run.capability == capability,
            Run.status.in_(ACTIVE),
        )
        .limit(1)
    )
    # Model preparation is shared infrastructure. Expose only a busy boolean,
    # while ordinary health/index/search coalescing remains owner-scoped.
    active = (
        session.connection().scalar(busy)
        if isinstance(session, ScopedSession) and capability == "memory.embed.prepare"
        else session.scalar(busy)
    )
    if active:
        raise HTTPException(409, "Cancel the active embeddings Run before starting another")
    task = task or create_task(session, title=title, prompt=title, capability=capability)
    run = create_run(
        session,
        task,
        run_type="memory",
        capability=capability,
        executor_type="memory_embed",
        execution_target="container",
        parameters={
            "endpoint": setup["endpoint"],
            "model": setup["model"],
            "secret_ref": "" if isinstance(session, ScopedSession) else setup["secret_ref"],
            "backend": setup["backend"],
            "model_id": setup["model_id"],
            "revision": setup["revision"],
            "embedding_identity": vector_identity(setup),
            "execution_deadline_at": parent.parameters["execution_deadline_at"]
            if parent
            else (utcnow() + timedelta(minutes=10)).isoformat(),
            **extra,
        },
        parent_run_id=parent.id if parent else None,
        permissions=(["manage_models"] + (["network_read"] if extra.get("confirm_download") is True else []))
        if capability == "memory.embed.prepare"
        else [],
        requested_resources={"cpu_threads": 2, "ram_limit_bytes": 2 * 1024**3}
        if setup["backend"] == "local_cpu" or capability == "memory.embed.prepare"
        else {},
        retry_class="inspect",
        triggered_by="user",
    )
    if parent:
        from app.dependencies import depend_on

        depend_on(session, run, parent)
    return run


@router.post("/prepare", status_code=202)
def prepare_local(body: PrepareBody, session: DB):
    setup = load_setup(session)
    if body.expected_revision != setup["revision"]:
        raise HTTPException(409, "Memory settings changed. Reload before preparing a model.")
    if not dependencies_available():
        raise HTTPException(409, "This application image does not include the CPU embedding engine")
    if not body.confirm_download and not installation(get_settings().data_dir)["installed"]:
        raise HTTPException(422, "Explicitly confirm the model download first")
    run = _enqueue(
        session,
        capability="memory.embed.prepare",
        title="Prepare local semantic memory",
        setup=setup,
        extra={"confirm_download": body.confirm_download, "requested_model_id": body.model_id},
    )
    setup["prepare_run_id"] = run.id
    save_setup(session, setup)
    session.commit()
    return run_dict(run)


@router.post("/health", status_code=202)
def health(session: DB):
    setup = require_setup(session)
    run = _enqueue(
        session,
        capability="memory.embed.health",
        title="Check memory embeddings endpoint",
        extra={},
        setup=setup,
    )
    setup["last_health_run_id"] = run.id
    save_setup(session, setup)
    session.commit()
    return run_dict(run)


@router.post("/index", status_code=202)
def index_memories(session: DB):
    setup = require_setup(session)
    run = _enqueue(
        session,
        capability="memory.embed.index",
        title="Index memory embeddings",
        extra={"batch_size": INDEX_BATCH, "all_memories": True},
        setup=setup,
    )
    setup["last_index_run_id"] = run.id
    save_setup(session, setup)
    session.commit()
    return run_dict(run)


@router.post("/search", status_code=202)
def search_memories(body: SearchBody, session: DB):
    setup = require_setup(session)
    run = _enqueue(
        session,
        capability="memory.embed.search",
        title="Semantic memory search",
        extra={
            "query": body.query,
            "limit": SEARCH_LIMIT,
            "scope": body.scope,
            "scope_id": str(body.scope_id) if body.scope_id else None,
        },
        setup=setup,
    )
    session.commit()
    return run_dict(run)


async def embed_text(endpoint: str, model: str, text: str, secret_ref: str) -> list[float]:
    if not (text or "").strip():
        raise ProviderError("Refusing to embed empty text")
    url = endpoint.rstrip("/") + "/embeddings"
    headers = authorization_headers(secret_ref, required=False)
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.post(
                url,
                json={"model": model, "input": text[:MAX_INPUT]},
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise ProviderError("The embeddings endpoint is unreachable") from exc
    if response.is_redirect:
        raise ProviderError("Embeddings redirects are not followed")
    if response.status_code >= 400:
        raise ProviderError(f"Embeddings endpoint returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("Embeddings endpoint did not return JSON") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ProviderError("Embeddings endpoint returned no vector")
    try:
        return validate_vector(data[0].get("embedding"))
    except ValueError as exc:
        raise ProviderError(str(exc)) from exc


class MemoryEmbedExecutor:
    name = "memory_embed"

    def execute(self, session, run):
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        try:
            result = asyncio.run(self._run(session, run))
            if result is None:
                session.refresh(run)
                if run.status == "cancel_requested":
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return "done"
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return "done"
            if run.status != "running":
                return "done"
            if run.capability != "memory.embed.prepare":
                validate_binding(session, run)
            if run.capability in {"memory.embed.index", "memory.embed.search"}:
                _write_json(
                    session,
                    run,
                    "memory-embeddings-"
                    + ("index" if run.capability.endswith("index") else "search")
                    + ".json",
                    result,
                )
            run.metadata_json = {**run.metadata_json, **result}
            run.summary = result.get("summary") or "Embeddings Run completed."
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload=result)
            session.commit()
        except Exception as exc:
            session.rollback()
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            elif run.status not in {"canceled", "interrupted", "failed", "succeeded"}:
                mark_failed(session, run, type(exc).__name__, str(exc) or "Embeddings Run failed")
        return "done"

    async def _run(self, session, run):
        cpu = None
        try:
            remaining = 600
            if run.parameters.get("execution_deadline_at"):
                remaining = min(
                    600,
                    (
                        datetime.fromisoformat(run.parameters["execution_deadline_at"]) - utcnow()
                    ).total_seconds(),
                )
            if remaining <= 0:
                raise TimeoutError("The semantic memory execution budget expired")
            async with asyncio.timeout(remaining):
                if run.capability == "memory.embed.prepare":
                    return await self._prepare(session, run)
                bound = validate_binding(session, run)
                if run.parameters.get("backend") == "local_cpu":
                    cpu = CpuEmbeddingProcess(session, run, get_settings().data_dir)

                    async def encode(text, kind):
                        if cpu.process is None:
                            await cpu.open()
                        return await cpu.encode(text, kind)
                else:

                    async def encode(text, kind):
                        return validate_vector(
                            await embed_text(
                                run.parameters["endpoint"],
                                run.parameters["model"],
                                text,
                                bound["secret_ref"],
                            )
                        )

                if run.capability == "memory.embed.health":
                    check_running(session, run)
                    vector = await encode(PROBE_TEXT, "query")
                    check_running(session, run)
                    setup = validate_binding(session, run)
                    setup["dimension"] = len(vector)
                    setup["last_health_run_id"] = run.id
                    save_setup(session, setup)
                    return {
                        "dimension": len(vector),
                        "model": setup["model"],
                        "stored": False,
                        "summary": f"Embedding model returned a {len(vector)}-dimension vector.",
                    }
                if run.capability == "memory.embed.index":
                    return await self._index(session, run, encode)
                if run.capability == "memory.embed.search":
                    return await self._search(session, run, encode)
                raise ValueError("Unknown embeddings capability")
        except EmbeddingStopped:
            return None
        finally:
            if cpu is not None:
                await cpu.close()

    async def _prepare(self, session, run):
        from app.embedding_download import prepare_files
        from app.permissions import require
        from app.task_control import lock_task

        for permission in (
            ["manage_models", "network_read"]
            if run.parameters.get("confirm_download") is True
            else ["manage_models"]
        ):
            require(run.effective_permissions, permission)
        if run.parameters.get("requested_model_id") != MODEL_ID:
            raise ValueError("Unknown pinned local embedding model")
        current = load_setup(session)
        if current["revision"] != run.parameters["revision"] or current["prepare_run_id"] != run.id:
            raise ValueError("Memory preparation was superseded by newer settings")
        session.commit()
        await prepare_files(
            session,
            run,
            get_settings().data_dir,
            allow_download=run.parameters.get("confirm_download") is True,
        )
        cpu = CpuEmbeddingProcess(session, run, get_settings().data_dir)
        try:
            await cpu.open()
            vector = validate_vector(await cpu.encode(PROBE_TEXT, "query"))
            if len(vector) != DIMENSION:
                raise ValueError("Local model returned the wrong embedding dimension")
        finally:
            await cpu.close()
        check_running(session, run)
        lock_task(session, run.task)
        current = load_setup(session)
        if (
            current["revision"] != run.parameters["revision"]
            or current["prepare_run_id"] != run.id
            or run.task.metadata_json.get("stop_requested_at")
        ):
            raise ValueError("Memory settings changed before preparation completed")
        setup = {
            "backend": "local_cpu",
            "revision": current["revision"] + 1,
            "model_id": MODEL_ID,
            "model": MODEL_ID,
            "endpoint": "",
            "secret_ref": "",
            "dimension": len(vector),
            "prepare_run_id": run.id,
            "last_health_run_id": run.id,
        }
        _activate_prepared_model(session, run, setup)
        saved = load_setup(session)
        indexed = _enqueue(
            session,
            capability="memory.embed.index",
            title="Index memories with the local CPU model",
            extra={"all_memories": True, "batch_size": INDEX_BATCH},
            setup=saved,
            task=run.task,
            parent=run,
        )
        saved["last_index_run_id"] = indexed.id
        save_setup(session, saved)
        return {
            "dimension": len(vector),
            "model": MODEL_ID,
            "device": "CPU",
            "index_run_id": indexed.id,
            "summary": "Local CPU semantic memory is ready. Memory indexing was queued.",
        }

    async def _index(self, session, run, encode):
        ids = list(
            session.scalars(
                select(MemoryEntry.id).where(MemoryEntry.enabled.is_(True)).order_by(MemoryEntry.id)
            )
        )
        identity = run.parameters.get("embedding_identity") or run.parameters["model"]
        indexed, skipped, changed, indexed_count = [], 0, 0, 0
        for key in ids:
            check_running(session, run)
            validate_binding(session, run)
            entry = session.get(MemoryEntry, key, populate_existing=True)
            if entry is None or not entry.enabled:
                changed += 1
                session.commit()
                continue
            digest = content_hash(entry.content)
            scope = (entry.scope, entry.scope_id)
            existing = session.get(MemoryEmbedding, entry.id)
            if existing and existing.model == identity and existing.content_hash == digest:
                skipped += 1
                session.commit()
                continue
            if not run.parameters.get("all_memories") and indexed_count >= int(
                run.parameters.get("limit") or INDEX_BATCH
            ):
                break
            text = entry.content
            append_event(session, run.id, "embedding.started", {"memory_id": key})
            session.commit()
            vector = validate_vector(await encode(text, "passage"))
            check_running(session, run)
            setup = validate_binding(session, run)
            entry = session.get(MemoryEntry, key, populate_existing=True)
            if (
                entry is None
                or not entry.enabled
                or content_hash(entry.content) != digest
                or (entry.scope, entry.scope_id) != scope
            ):
                changed += 1
                session.commit()
                continue
            if setup["dimension"] is not None and len(vector) != setup["dimension"]:
                raise ValueError("Embedding dimensions changed; check the selected model")
            now = utcnow()
            existing = session.get(MemoryEmbedding, key)
            if existing is None:
                existing = MemoryEmbedding(memory_id=key, created_at=now)
                session.add(existing)
            existing.vector, existing.dimension, existing.model = vector, len(vector), identity
            existing.content_hash, existing.source_run_id, existing.updated_at = digest, run.id, now
            indexed_count += 1
            if len(indexed) < 200:
                indexed.append(key)
            run.metadata_json = {
                **run.metadata_json,
                "embedding_progress": {
                    "indexed": indexed_count,
                    "skipped_current": skipped,
                    "changed": changed,
                    "total": len(ids),
                },
            }
            append_event(session, run.id, "embedding.stored", {"memory_id": key, "dimension": len(vector)})
            session.commit()
        check_running(session, run)
        validate_binding(session, run)
        report = {
            "indexed": indexed,
            "indexed_count": indexed_count,
            "ids_truncated": indexed_count > len(indexed),
            "skipped_current": skipped,
            "changed_during_index": changed,
            "model": run.parameters["model"],
            "summary": f"Indexed {indexed_count} memories; {skipped} already current; {changed} changed.",
        }
        return report

    async def _search(self, session, run, encode):
        query = run.parameters.get("query") or ""
        check_running(session, run)
        vector = validate_vector(await encode(query, "query"))
        check_running(session, run)
        validate_binding(session, run)
        identity = run.parameters.get("embedding_identity") or run.parameters["model"]
        statement = (
            select(MemoryEmbedding, MemoryEntry)
            .join(MemoryEntry)
            .where(MemoryEmbedding.model == identity, MemoryEntry.enabled.is_(True))
        )
        if run.parameters.get("scope"):
            statement = statement.where(MemoryEntry.scope == run.parameters["scope"])
        if run.parameters.get("scope_id"):
            statement = statement.where(MemoryEntry.scope_id == run.parameters["scope_id"])
        ranked = []
        for row, entry in session.execute(statement):
            if row.content_hash != content_hash(entry.content) or row.dimension != len(vector):
                continue
            score = cosine(vector, row.vector)
            if score is not None:
                ranked.append((score, entry, row.source_run_id))
        ranked.sort(key=lambda item: (-item[0], item[1].updated_at, item[1].id))
        hits = ranked[: int(run.parameters.get("limit") or SEARCH_LIMIT)]
        results = [
            {**memory_dict(entry), "score": round(score, 6), "embedding_run_id": source}
            for score, entry, source in hits
        ]
        report = {
            "query": query,
            "model": run.parameters["model"],
            "dimension": len(vector),
            "scope": run.parameters.get("scope"),
            "scope_id": run.parameters.get("scope_id"),
            "compared": len(ranked),
            "results": results,
            "summary": f"Compared {len(ranked)} current vectors; {len(results)} results.",
        }
        return report


def _write_json(session, run, filename, payload):
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
        json.dump(payload, handle)
        handle.flush()
        register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename=filename,
            run_id=run.id,
            metadata={"embeddings": True},
        )
