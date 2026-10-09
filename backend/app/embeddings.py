"""Optional memory embeddings from an explicit local OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
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
SETUP_FIELDS = ("endpoint", "model", "secret_ref", "last_health_run_id", "last_index_run_id", "dimension")
PROBE_TEXT = "ai-station embedding probe"
MAX_INPUT = 8000
INDEX_BATCH = 50
SEARCH_LIMIT = 30
MIN_DIM = 8
MAX_DIM = 4096


class SetupBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    endpoint: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    secret_ref: str = Field(default="", max_length=200)
    clear: StrictBool = False


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=2000)


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
    row = session.get(Setting, SETUP_KEY)
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    return {
        "endpoint": value.get("endpoint") or "",
        "model": value.get("model") or "",
        "secret_ref": value.get("secret_ref") or "",
        "last_health_run_id": value.get("last_health_run_id"),
        "last_index_run_id": value.get("last_index_run_id"),
        "dimension": value.get("dimension"),
        "configured": bool(value.get("endpoint") and value.get("model")),
    }


def save_setup(session, payload: dict) -> dict:
    row = session.get(Setting, SETUP_KEY)
    if row is None:
        row = Setting(key=SETUP_KEY, value={})
        session.add(row)
    row.value = {key: payload.get(key) for key in SETUP_FIELDS}
    session.flush()
    return load_setup(session)


def require_setup(session) -> dict:
    setup = load_setup(session)
    if not setup["configured"]:
        raise HTTPException(
            409,
            "Semantic memory requires an explicit local embeddings endpoint and model name. "
            "AI Station does not download embedding weights.",
        )
    return setup


def setup_view(session, setup=None):
    setup = setup or load_setup(session)
    indexed = session.scalar(select(func.count()).select_from(MemoryEmbedding)) or 0
    memories = session.scalar(select(func.count()).select_from(MemoryEntry)) or 0
    return {
        **{key: setup[key] for key in ("endpoint", "model", "configured", "dimension")},
        **public_secret(setup["secret_ref"]),
        "last_health_run_id": setup["last_health_run_id"],
        "last_index_run_id": setup["last_index_run_id"],
        "indexed_count": indexed,
        "memory_count": memories,
    }


@router.get("/setup")
def get_setup(session: DB):
    return setup_view(session)


@router.put("/setup")
def put_setup(body: SetupBody, session: DB):
    if body.clear:
        save_setup(session, {})
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


def _enqueue(session, *, capability, title, extra, setup):
    if session.scalar(
        select(Run.id).where(
            Run.executor_type == "memory_embed",
            Run.capability == capability,
            Run.status.in_(ACTIVE),
        )
    ):
        raise HTTPException(409, "Cancel the active embeddings Run before starting another")
    task = create_task(session, title=title, prompt=title, capability=capability)
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
            "secret_ref": setup["secret_ref"],
            **extra,
        },
        permissions=[],
        retry_class="inspect",
        triggered_by="user",
    )
    return run


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
        extra={"limit": INDEX_BATCH},
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
        extra={"query": body.query, "limit": SEARCH_LIMIT},
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
            run.metadata_json = {**run.metadata_json, **result}
            run.summary = result.get("summary") or "Embeddings Run completed."
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload=result)
            session.commit()
        except Exception as exc:
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            else:
                mark_failed(session, run, type(exc).__name__, str(exc) or "Embeddings Run failed")
        return "done"

    async def _run(self, session, run):
        params = run.parameters
        endpoint, model, secret_ref = params["endpoint"], params["model"], params.get("secret_ref") or ""
        if run.capability == "memory.embed.health":
            vector = await embed_text(endpoint, model, PROBE_TEXT, secret_ref)
            setup = load_setup(session)
            if setup["endpoint"] == endpoint and setup["model"] == model:
                setup["dimension"] = len(vector)
                setup["last_health_run_id"] = run.id
                save_setup(session, setup)
            return {
                "dimension": len(vector),
                "model": model,
                "stored": False,
                "summary": f"Embeddings endpoint returned a {len(vector)}-dimension vector. Nothing was stored.",
            }
        if run.capability == "memory.embed.index":
            return await self._index(session, run, endpoint, model, secret_ref)
        if run.capability == "memory.embed.search":
            return await self._search(session, run, endpoint, model, secret_ref)
        raise ValueError("Unknown embeddings capability")

    async def _index(self, session, run, endpoint, model, secret_ref):
        limit = int(run.parameters.get("limit") or INDEX_BATCH)
        candidates = list(
            session.scalars(
                select(MemoryEntry)
                .where(MemoryEntry.enabled.is_(True))
                .order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id)
                .limit(limit * 4)
            )
        )
        indexed, skipped = [], 0
        for entry in candidates:
            session.refresh(run)
            if run.status == "cancel_requested":
                return None
            digest = content_hash(entry.content)
            existing = session.get(MemoryEmbedding, entry.id)
            if existing and existing.model == model and existing.content_hash == digest:
                skipped += 1
                continue
            if len(indexed) >= limit:
                break
            append_event(session, run.id, "embedding.started", {"memory_id": entry.id})
            session.commit()
            vector = await embed_text(endpoint, model, entry.content, secret_ref)
            now = utcnow()
            if existing is None:
                existing = MemoryEmbedding(memory_id=entry.id, created_at=now)
                session.add(existing)
            existing.vector = vector
            existing.dimension = len(vector)
            existing.model = model
            existing.content_hash = digest
            existing.source_run_id = run.id
            existing.updated_at = now
            indexed.append(entry.id)
            append_event(
                session,
                run.id,
                "embedding.stored",
                {"memory_id": entry.id, "dimension": len(vector)},
            )
            session.commit()
        report = {
            "indexed": indexed,
            "skipped_current": skipped,
            "model": model,
            "summary": f"Indexed {len(indexed)} memories; {skipped} already current.",
        }
        _write_json(session, run, "memory-embeddings-index.json", report)
        return report

    async def _search(self, session, run, endpoint, model, secret_ref):
        query = run.parameters.get("query") or ""
        vector = await embed_text(endpoint, model, query, secret_ref)
        session.refresh(run)
        if run.status == "cancel_requested":
            return None
        rows = list(session.scalars(select(MemoryEmbedding).where(MemoryEmbedding.model == model)))
        ranked = []
        for row in rows:
            session.refresh(run)
            if run.status == "cancel_requested":
                return None
            entry = session.get(MemoryEntry, row.memory_id)
            if entry is None or not entry.enabled:
                continue
            if row.content_hash != content_hash(entry.content) or row.dimension != len(vector):
                continue
            score = cosine(vector, row.vector)
            if score is None:
                continue
            ranked.append((score, entry))
        ranked.sort(key=lambda item: (-item[0], item[1].updated_at, item[1].id))
        hits = ranked[: int(run.parameters.get("limit") or SEARCH_LIMIT)]
        results = []
        for score, entry in hits:
            stored = session.get(MemoryEmbedding, entry.id)
            results.append(
                {
                    **memory_dict(entry),
                    "score": round(score, 6),
                    "embedding_run_id": stored.source_run_id if stored else None,
                }
            )
        report = {
            "query": query,
            "model": model,
            "dimension": len(vector),
            "compared": len(ranked),
            "results": results,
            "summary": f"Compared {len(ranked)} current vectors; {len(results)} results.",
        }
        _write_json(session, run, "memory-embeddings-search.json", report)
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
