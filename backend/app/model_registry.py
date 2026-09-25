"""Read-only external model inventory. Discovery is a durable managed Run."""

import json
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifacts import adopt_existing
from app.config import get_settings
from app.db import session_scope, utcnow
from app.events import append_event
from app.models import ModelDefinition, ModelFile, Run
from app.paths import safe_join
from app.permissions import require
from app.runner_client import RunnerClient, RunnerError
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/models", tags=["models"])
DB = Annotated[Session, Depends(session_scope)]
Category = Literal["llm", "image", "video", "audio", "other"]


def file_dict(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "host_path",
            "filename",
            "size_bytes",
            "mtime",
            "format",
            "family",
            "quantization",
            "category",
            "capabilities",
            "root_label",
            "discovered_at",
            "last_seen_at",
            "last_scan_run_id",
            "availability",
        )
    }


@router.get("")
def models(
    session: DB,
    category: Category | None = None,
    q: str = Query("", max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    statement = select(ModelFile)
    if category:
        statement = statement.where(ModelFile.category == category)
    if q.strip():
        statement = statement.where(ModelFile.filename.icontains(q.strip(), autoescape=True))
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = session.scalars(statement.order_by(ModelFile.filename, ModelFile.id).limit(limit).offset(offset))
    latest = session.scalar(
        select(Run).where(Run.executor_type == "model_discovery").order_by(Run.created_at.desc()).limit(1)
    )
    return {
        "items": [file_dict(row) for row in rows],
        "total": total,
        "latest_scan": run_dict(latest) if latest else None,
    }


class DiscoverBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/discover", status_code=202)
def discover(body: DiscoverBody, session: DB):
    if session.scalar(
        select(Run.id).where(Run.executor_type == "model_discovery", Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "A model discovery Run is already active")
    task = create_task(
        session,
        title="Discover installed models",
        prompt="Read metadata from configured host model roots",
        capability="models.discover",
    )
    run = create_run(
        session,
        task,
        run_type="discovery",
        capability="models.discover",
        executor_type="model_discovery",
        execution_target="host",
        permissions=["filesystem_read", "manage_models"],
        retry_class="safe",
        parameters={},
    )
    session.commit()
    return run_dict(run)


@router.get("/{file_id}")
def model_detail(file_id: UUID, session: DB):
    row = session.get(ModelFile, str(file_id))
    if row is None:
        raise HTTPException(404, "Model file not found")
    definitions = session.scalars(select(ModelDefinition).where(ModelDefinition.file_id == row.id))
    return {
        **file_dict(row),
        "definitions": [
            {"id": d.id, "name": d.name, "category": d.category, "capabilities": d.capabilities}
            for d in definitions
        ],
    }


class DiscoveredFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host_path: str = Field(min_length=1, max_length=1200)
    filename: str = Field(min_length=1, max_length=400)
    size_bytes: int = Field(ge=0)
    mtime: float = Field(allow_inf_nan=False)
    format: str = Field(max_length=40)
    family: str = Field(max_length=80)
    quantization: str = Field(max_length=40)
    category: Category
    capabilities: list[str] = Field(max_length=10)
    root_label: str = Field(max_length=200)


class RootObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=200)
    status: Literal["scanned", "unavailable"]


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    models: list[DiscoveredFile] = Field(max_length=5000)
    roots: list[RootObservation] = Field(max_length=100)


class ModelDiscoveryExecutor:
    name = "model_discovery"

    def execute(self, session, run):
        for permission in ("filesystem_read", "manage_models"):
            require(run.effective_permissions, permission)
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        session.commit()
        runner = RunnerClient()
        try:
            process = runner.request(
                "POST", "/v1/runs/model-scan", {"run_id": run.id, "permissions": run.effective_permissions}
            )
        except RunnerError as exc:
            if exc.status_code < 500:
                mark_failed(session, run, "RunnerRejected", str(exc))
                return "done"
            raise
        session.refresh(run)
        run.pid, run.process_group_id = process["pid"], process["process_group_id"]
        run.stdout_log, run.stderr_log = process["stdout_log"], process["stderr_log"]
        run.runner_id = process.get("runner_id")
        if run.status != "cancel_requested":
            transition(session, run, RunStatus.RUNNING, event_type="executor.started", payload={})
        session.commit()
        offsets = {"stdout_offset": 0, "stderr_offset": 0}
        while True:
            session.refresh(run)
            canceled = run.status == "cancel_requested"
            session.commit()
            if canceled:
                runner.cancel_process(run.id)
            process = runner.inspect_process(run.id, **offsets)
            for stream in ("stdout", "stderr"):
                if process.get(stream):
                    append_event(session, run.id, stream, {"text": process[stream]})
                offsets[f"{stream}_offset"] = process[f"{stream}_offset"]
            session.commit()
            if not process["alive"] and not process["stdout_more"] and not process["stderr_more"]:
                break
            if not process["stdout_more"] and not process["stderr_more"]:
                time.sleep(0.2)
        session.refresh(run)
        run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
        if run.status == "cancel_requested" or process["status"] == "canceled":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        if process["status"] == "interrupted" or process.get("exit_code") is None:
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Scan exit status unavailable"},
            )
            return "done"
        if process["exit_code"] != 0:
            mark_failed(
                session, run, "ModelScanFailed", process.get("stderr_tail") or "Model discovery failed"
            )
            return "done"
        relative = f"artifacts/{run.id[:2]}/{run.id[2:4]}/{run.id}.json"
        output = safe_join(get_settings().data_dir, relative)
        if output.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Discovery report exceeds size limit")
        report = Inventory.model_validate(json.loads(output.read_text()))
        if str(report.run_id) != run.id:
            raise ValueError("Discovery report belongs to a different Run")
        now = utcnow()
        complete_roots = {root.path for root in report.roots if root.status == "scanned"}
        existing = {row.host_path: row for row in session.scalars(select(ModelFile))}
        for row in existing.values():
            row.availability = "missing" if row.root_label in complete_roots else "unknown"
            row.last_scan_run_id = run.id
        for item in report.models:
            if item.root_label not in complete_roots:
                raise ValueError("Discovered file is not associated with a completed root")
            row = existing.get(item.host_path)
            if row is None:
                row = ModelFile(**item.model_dump())
                existing[item.host_path] = row
                session.add(row)
            else:
                for key, value in item.model_dump().items():
                    setattr(row, key, value)
            row.availability, row.last_seen_at, row.last_scan_run_id = "present", now, run.id
        adopt_existing(
            session,
            relative_path=relative,
            artifact_type="json",
            mime_type="application/json",
            original_filename="model-inventory.json",
            run_id=run.id,
            metadata={"model_count": len(report.models), "metadata_only": True},
        )
        append_event(
            session,
            run.id,
            "models.discovered",
            {"count": len(report.models), "roots": [root.model_dump() for root in report.roots]},
        )
        run.summary = f"Observed {len(report.models)} model files; external files were not modified."
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        return "done"
