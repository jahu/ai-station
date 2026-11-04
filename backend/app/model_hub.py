"""Private durable inspections of public model sources, never HTTP inference/download."""

import asyncio
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.hub_sources import inspect_source, parse_source, search_models, search_query
from app.model_hardware import assess_file
from app.model_setup import administrator, fingerprint, storage_info
from app.models import Run, Task
from app.permissions import require
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, request_cancel, run_dict, touch_lease, transition
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/model-hub", tags=["model discovery"])
DB = Annotated[Session, Depends(session_scope)]
INTENT = "model.hub.inspect"


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    source: str = Field(min_length=3, max_length=1800)

    @field_validator("source")
    @classmethod
    def valid_source(cls, value):
        parse_source(value)
        return value


@router.post("/inspections", status_code=202)
def inspect_model(body: InspectRequest, session: DB):
    return enqueue_inspection(
        session, body.client_request_id, {"source": parse_source(body.source).model_dump(mode="json")}
    )


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    query: str = Field(min_length=2, max_length=100)

    @field_validator("query")
    @classmethod
    def valid_query(cls, value):
        return search_query(value)


@router.post("/searches", status_code=202)
def search(body: SearchRequest, session: DB):
    return enqueue_inspection(session, body.client_request_id, {"query": body.query})


def enqueue_inspection(session, client_request_id, request):
    administrator(session)
    task = session.get(Task, str(client_request_id))
    if task is not None:
        if task.intent != INTENT or task.metadata_json.get("request") != request:
            raise HTTPException(409, "This request ID belongs to another inspection")
        run = session.get(Run, task.metadata_json.get("inspection_run_id"))
        if run is None:
            raise HTTPException(409, "The original inspection requires review")
        return run_dict(run)
    task = Task(
        id=str(client_request_id),
        title="Inspect model source" if "source" in request else "Find new models",
        prompt="Inspect public publisher metadata and estimate compatibility; do not download weights",
        intent=INTENT,
        capability="models.inspect_source",
        metadata_json={"request": request},
    )
    try:
        session.add(task)
        session.flush()
        run = create_run(
            session,
            task,
            run_type="inspection",
            capability="models.inspect_source",
            executor_type="model_hub_inspect",
            execution_target="container",
            parameters={
                **request,
                "execution_deadline_at": (utcnow() + timedelta(minutes=3)).isoformat(),
            },
            permissions=["network_read", "filesystem_read", "workspace_write", "manage_models"],
            retry_class="safe",
        )
        task.metadata_json = {**task.metadata_json, "inspection_run_id": run.id}
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "This inspection request was submitted concurrently; retry its ID") from exc
    return run_dict(run)


class InspectionStopped(Exception):
    pass


class InspectionClaimLost(Exception):
    pass


class ModelHubExecutor:
    name = "model_hub_inspect"

    def execute(self, session, run):
        for permission in ("network_read", "filesystem_read", "workspace_write", "manage_models"):
            require(run.effective_permissions, permission)
        claim = (run.worker_id, run.claimed_at)

        def check():
            session.refresh(run)
            if (run.worker_id, run.claimed_at) != claim:
                session.rollback()
                raise InspectionClaimLost()
            cancel_expired_run(session, run.id)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                raise InspectionStopped()
            if run.status in TERMINAL:
                session.rollback()
                raise InspectionStopped()
            if run.owner_id:
                from app.models import User

                owner = session.get(User, run.owner_id, populate_existing=True)
                if owner is None or not owner.enabled or not owner.is_admin:
                    raise ValueError("Model inspection administrator authority changed")
            touch_lease(session, run)
            session.commit()

        try:
            check()
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            append_event(
                session, run.id, "model.source_inspection", {"provider": "huggingface", "metadata_only": True}
            )
            session.commit()

            async def inspect():
                async with asyncio.timeout(90):
                    from app.hub_sources import HubSource

                    if "source" in run.parameters:
                        return await inspect_source(HubSource.model_validate(run.parameters["source"]), check)
                    return await search_models(run.parameters["query"], check)

            report = asyncio.run(inspect())
            check()
            hardware = {"storage_unavailable": True}
            if report.get("kind") != "search":
                try:
                    hardware = RunnerClient(timeout=8).hardware()
                except (RunnerError, RunnerUnavailable):
                    pass
            check()
            storage = storage_info(hardware) if report.get("kind") != "search" else None
            for file in report["files"]:
                file["assessment"] = assess_file(file, hardware, storage)
            report.update(
                observed_at=utcnow().isoformat(),
                hardware_observed=not hardware.get("storage_unavailable", False),
                no_weights_downloaded=True,
            )
            report["observation_sha256"] = fingerprint(report)
            check()
            # Publication and Stop share the normal Task fence. Report paths are
            # UUID-owned; neither source metadata nor clients select filenames.
            from app.task_control import lock_task

            lock_task(session, run.task)
            session.refresh(run)
            if (run.worker_id, run.claimed_at) != claim:
                raise InspectionClaimLost()
            cancel_expired_run(session, run.id)
            if run.task.metadata_json.get("stop_requested_at") and run.status not in TERMINAL:
                if run.status != "cancel_requested":
                    request_cancel(session, run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                return "done"
            if run.status != "running":
                session.rollback()
                return "done"
            if run.owner_id:
                from app.models import User

                owner = session.get(User, run.owner_id, populate_existing=True, with_for_update=True)
                if owner is None or not owner.enabled or not owner.is_admin:
                    raise ValueError("Model inspection administrator authority changed before publication")
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as source:
                json.dump(report, source)
                source.flush()
                artifact = register_file(
                    session,
                    source=Path(source.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename="model-source-inspection.json",
                    run_id=run.id,
                    metadata={"model_source_inspection": True},
                )
            run.metadata_json = {
                **run.metadata_json,
                "source_inspection": report,
                "inspection_artifact_id": artifact.id,
            }
            run.summary = (
                f"Inspected {report['repository']}: {len(report['files'])} weight files; no weights downloaded."
                if "repository" in report
                else f"Found {len(report['items'])} model repositories; review compatibility before installing."
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            session.commit()
        except (InspectionStopped, InspectionClaimLost):
            session.rollback()
        return "done"
