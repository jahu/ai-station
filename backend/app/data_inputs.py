"""Stored data inputs and ordinary queued read-only inspection Runs."""

import hashlib
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.data_preview import inspect_csv, inspect_xlsx
from app.db import session_scope
from app.events import append_event
from app.models import Artifact
from app.permissions import require
from app.python_execution import MAX_INPUT, input_snapshots, read_owned_file
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.serialize import artifact_dict
from app.state import RunStatus

router = APIRouter(prefix="/api/data", tags=["data"])
DB = Annotated[Session, Depends(session_scope)]


class DataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: UUID


def enqueue_inspection(session, artifact_id):
    snapshot = input_snapshots(session, [artifact_id])[0]
    if snapshot["suffix"] not in {".csv", ".xlsx"}:
        raise ValueError("Choose a CSV or XLSX input")
    artifact = session.get(Artifact, str(artifact_id))
    task = create_task(
        session,
        title=f"Inspect {artifact.original_filename}",
        prompt="Read-only data preview",
        capability="data.inspect",
    )
    run = create_run(
        session,
        task,
        run_type="inspection",
        capability="data.inspect",
        executor_type="data_inspection",
        execution_target="container",
        permissions=["filesystem_read"],
        retry_class="safe",
        parameters={"input": snapshot},
    )
    artifact.metadata_json = {**artifact.metadata_json, "data_inspection_run_id": run.id}
    return run


@router.post("/uploads", status_code=201)
def upload(session: DB, file: Annotated[UploadFile, File()]):
    name = Path((file.filename or "").replace("\\", "/")).name[:200]
    suffix = Path(name).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(422, "Import a CSV or XLSX data file")
    data = file.file.read(MAX_INPUT + 1)
    if not data or len(data) > MAX_INPUT:
        raise HTTPException(413, "Data files must contain 1 byte to 16 MiB")
    with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
        temporary.write(data)
        temporary.flush()
        artifact = register_file(
            session,
            source=Path(temporary.name),
            artifact_type="document",
            mime_type="text/csv"
            if suffix == ".csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            original_filename=name,
            run_id=None,
            metadata={"source": "upload", "data_input": True},
        )
    enqueue_inspection(session, artifact.id)
    session.commit()
    return artifact_dict(artifact)


@router.post("/inspections", status_code=202)
def inspect(body: DataRequest, session: DB):
    try:
        run = enqueue_inspection(session, body.artifact_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return run_dict(run)


class DataInspectionExecutor:
    name = "data_inspection"

    def execute(self, session, run):
        require(run.effective_permissions, "filesystem_read")
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        end, checks = time.monotonic() + 30, 0

        def check():
            nonlocal checks
            checks += 1
            if time.monotonic() >= end:
                raise ValueError("Data inspection exceeded 30 seconds")
            if checks % 128 == 1:
                session.refresh(run, attribute_names=["status"])
                session.commit()
                if run.status == "cancel_requested":
                    raise InterruptedError("Inspection stopped")

        try:
            snapshot = run.parameters["input"]
            if input_snapshots(session, [snapshot["artifact_id"]])[0] != snapshot:
                raise ValueError("Data input metadata changed after enqueue")
            from app.paths import artifact_relative

            path = read_owned_file(
                artifact_relative(snapshot["artifact_id"], snapshot["suffix"]),
                snapshot["size_bytes"],
                snapshot["sha256"],
                limit=MAX_INPUT,
            )
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != snapshot["size_bytes"]:
                    raise ValueError("Data input changed before inspection")
                data = handle.read(MAX_INPUT + 1)
                after = os.fstat(handle.fileno())
                if (
                    len(data) != snapshot["size_bytes"]
                    or hashlib.sha256(data).hexdigest() != snapshot["sha256"]
                    or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise ValueError("Data input changed before inspection")
            check()
            preview = (inspect_csv if snapshot["suffix"] == ".csv" else inspect_xlsx)(data, check)
            session.refresh(run, attribute_names=["status"])
            if run.status == "cancel_requested":
                raise InterruptedError("Inspection stopped")
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as output:
                json.dump(preview, output)
                output.flush()
                artifact = register_file(
                    session,
                    source=Path(output.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename="data-preview.json",
                    run_id=run.id,
                    parent_artifact_ids=[snapshot["artifact_id"]],
                    metadata={"data_preview": True, "input_sha256": snapshot["sha256"]},
                )
            run.metadata_json = {
                **run.metadata_json,
                "data_preview": preview,
                "preview_artifact_id": artifact.id,
            }
            run.summary = f"Inspected {len(preview['sheets'])} data sheet(s); source unchanged."
            append_event(
                session,
                run.id,
                "data.inspected",
                {"artifact_id": artifact.id, "input_artifact_id": snapshot["artifact_id"]},
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        except Exception as exc:
            session.refresh(run, attribute_names=["status"])
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            else:
                mark_failed(session, run, "DataInspectionFailed", str(exc)[:500])
        return "done"
