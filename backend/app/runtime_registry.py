"""Inspectable external runtime observations through the shared Run engine."""

import json
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.events import append_event
from app.local_provider import LocalChatProvider, local_endpoint
from app.models import Run, Runtime, RuntimeInstance
from app.permissions import require
from app.providers import ProviderError
from app.runner_client import RunnerClient
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.serialize import runtime_dict
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/runtimes", tags=["runtimes"])
DB = Annotated[Session, Depends(session_scope)]
FAMILIES = {
    "llama.cpp": "llama.cpp",
    "ollama": "Ollama",
    "stable-diffusion.cpp": "stable-diffusion.cpp",
    "comfyui": "ComfyUI",
    "openai-compatible": "Local compatible endpoint",
}


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_key: Literal["llama.cpp", "ollama", "stable-diffusion.cpp", "comfyui"]
    pid: int = Field(ge=1)
    start_ticks: int = Field(ge=0)


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instances: list[Observation] = Field(max_length=200)
    complete: StrictBool
    inspected: int = Field(ge=0, le=20000)


@router.get("")
def runtimes(session: DB, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    rows = session.scalars(
        select(RuntimeInstance)
        .order_by(RuntimeInstance.updated_at.desc(), RuntimeInstance.id)
        .limit(limit)
        .offset(offset)
    )
    latest = session.scalar(
        select(Run).where(Run.executor_type == "runtime_observation").order_by(Run.created_at.desc()).limit(1)
    )
    cutoff = utcnow() - timedelta(minutes=5)
    return {
        "items": [{**runtime_dict(row), "stale": row.updated_at < cutoff} for row in rows],
        "total": session.scalar(select(func.count()).select_from(RuntimeInstance)),
        "latest_scan": run_dict(latest) if latest else None,
    }


@router.post("/observe", status_code=202)
def enqueue(body: EmptyBody, session: DB):
    if session.scalar(
        select(Run.id).where(Run.executor_type == "runtime_observation", Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "Runtime observation is already active")
    task = create_task(
        session,
        title="Observe external runtimes",
        prompt="Read process metadata and configured local endpoint health",
        capability="runtimes.observe",
    )
    run = create_run(
        session,
        task,
        run_type="discovery",
        capability="runtimes.observe",
        executor_type="runtime_observation",
        execution_target="container",
        permissions=["filesystem_read"],
        retry_class="safe",
        parameters={},
    )
    session.commit()
    return run_dict(run)


def upsert_instance(session, *, identity, runtime_key, status, endpoint="", metadata):
    if session.scalar(select(Runtime.id).where(Runtime.key == runtime_key)) is None:
        session.add(Runtime(key=runtime_key, name=FAMILIES[runtime_key], kind="inference"))
    instance_id = str(uuid5(NAMESPACE_URL, "ai-station:local-runtime:" + identity))
    row = session.get(RuntimeInstance, instance_id)
    if row is None:
        row = RuntimeInstance(
            id=instance_id, runtime_key=runtime_key, name=FAMILIES[runtime_key], ownership="external"
        )
        session.add(row)
    # Only this observer's records are mutable here. No import of managed rows.
    if row.ownership != "external":
        raise ValueError("Observation cannot replace a managed runtime")
    row.status, row.endpoint, row.metadata_json, row.updated_at = status, endpoint, metadata, utcnow()
    session.flush()
    return row.id


class RuntimeObservationExecutor:
    name = "runtime_observation"

    @staticmethod
    def canceled(session, run):
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            session.commit()
            return True
        session.commit()
        return run.status in TERMINAL

    def execute(self, session, run):
        try:
            if self.canceled(session, run):
                return "done"
            require(run.effective_permissions, "filesystem_read")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
            transition(
                session, run, RunStatus.RUNNING, event_type="executor.started", payload={"mode": "read_only"}
            )
            session.commit()
            inventory = Inventory.model_validate(RunnerClient(timeout=5).observe_runtimes())
            if self.canceled(session, run):
                return "done"
            endpoint = ""
            models = []
            endpoint_status, endpoint_error = "unknown", ""
            try:
                endpoint = local_endpoint()
                models = LocalChatProvider().models()[:200]
                endpoint_status = "available"
            except ProviderError as exc:
                endpoint_status, endpoint_error = "unavailable", str(exc)
            if self.canceled(session, run):
                return "done"
            seen = set()
            for item in inventory.instances:
                seen.add(
                    upsert_instance(
                        session,
                        identity=item.identity,
                        runtime_key=item.runtime_key,
                        status="observed",
                        metadata={
                            "source": "host_process",
                            "runner": "local",
                            "pid": item.pid,
                            "start_ticks": item.start_ticks,
                            "scan_run_id": run.id,
                        },
                    )
                )
            # Only records belonging to this local process observer are reconciled.
            for row in session.scalars(
                select(RuntimeInstance).where(RuntimeInstance.ownership == "external")
            ):
                if (
                    row.metadata_json.get("source") == "host_process"
                    and row.metadata_json.get("runner") == "local"
                    and row.id not in seen
                ):
                    row.status = "not_observed" if inventory.complete else "unknown"
                    row.updated_at = utcnow()
                    row.metadata_json = {**row.metadata_json, "scan_run_id": run.id}
                elif row.metadata_json.get("source") == "configured_endpoint" and row.endpoint != endpoint:
                    row.status = "unconfigured"
                    row.updated_at = utcnow()
            if endpoint:
                upsert_instance(
                    session,
                    identity="endpoint:" + endpoint,
                    runtime_key="openai-compatible",
                    status=endpoint_status,
                    endpoint=endpoint,
                    metadata={
                        "source": "configured_endpoint",
                        "models": models,
                        "error": endpoint_error,
                        "scan_run_id": run.id,
                    },
                )
            report = {
                **inventory.model_dump(),
                "endpoint": {
                    "url": endpoint,
                    "status": endpoint_status,
                    "models": models,
                    "error": endpoint_error,
                },
            }
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
                json.dump(report, handle)
                handle.flush()
                register_file(
                    session,
                    source=Path(handle.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename="runtime-observations.json",
                    run_id=run.id,
                )
            append_event(
                session,
                run.id,
                "runtimes.observed",
                {"processes": len(seen), "complete": inventory.complete, "endpoint_status": endpoint_status},
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        except Exception as exc:
            session.rollback()
            if not self.canceled(session, run):
                mark_failed(session, run, type(exc).__name__, str(exc))
        return "done"
