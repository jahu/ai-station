"""Private durable inspections of public model sources, never HTTP inference/download."""

import asyncio
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal
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


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    search_run_id: UUID
    observation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_target: Literal[32768, 131072] = 32768


@router.post("/comparisons", status_code=202)
def compare(body: CompareRequest, session: DB):
    from app.hub_observations import search

    administrator(session)
    search(session, body.search_run_id, body.observation_sha256)
    return enqueue_inspection(
        session,
        body.client_request_id,
        {
            "comparison": {
                "search_run_id": str(body.search_run_id),
                "observation_sha256": body.observation_sha256,
                "context_target": body.context_target,
            }
        },
    )


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
        title="Inspect model source"
        if "source" in request
        else "Compare model hardware fit"
        if "comparison" in request
        else "Plan model installation"
        if "planning" in request
        else "Find new models",
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

            comparison_hardware = {"storage_unavailable": True}
            comparison_storage = None
            if "comparison" in run.parameters:
                try:
                    comparison_hardware = RunnerClient(timeout=8).hardware()
                except (RunnerError, RunnerUnavailable):
                    pass
                check()
                comparison_storage = storage_info(comparison_hardware)

            async def inspect():
                async with asyncio.timeout(90):
                    from app.hub_sources import HubSource

                    if "comparison" in run.parameters:
                        from app.hub_comparisons import inspect as inspect_comparison

                        return await inspect_comparison(
                            session, run, check, inspect_source, comparison_hardware, comparison_storage
                        )

                    if "planning" in run.parameters:
                        from app.hub_candidates import resolve_candidate
                        from app.hub_installations import source_observation

                        plan = run.parameters["planning"]
                        observation = source_observation(
                            session, plan["inspection_run_id"], plan["observation_sha256"]
                        )
                        check()
                        candidate = await resolve_candidate(
                            observation, plan["filename"], check, plan.get("context_target", 131072)
                        )
                        file = next(
                            dict(f) for f in observation["files"] if f["filename"] == plan["filename"]
                        )
                        return {
                            "kind": "install_plan",
                            "repository": candidate.repository,
                            "revision": candidate.revision,
                            "source_url": candidate.source_url,
                            "license_url": candidate.license_url,
                            "license": candidate.license,
                            "candidate": candidate.model_dump(mode="json"),
                            "manifest_sha256": fingerprint(candidate.model_dump(mode="json")),
                            "source_inspection_run_id": plan["inspection_run_id"],
                            "source_inspection_repository": observation["repository"],
                            "files": [file],
                            "metadata_only": True,
                            "context_target": plan.get("context_target", 131072),
                        }
                    if "source" in run.parameters:
                        from app.model_variant_advice import enrich_source

                        report = await inspect_source(
                            HubSource.model_validate(run.parameters["source"]), check
                        )
                        await enrich_source(report, check)
                        return report
                    return await search_models(run.parameters["query"], check)

            report = asyncio.run(inspect())
            check()
            hardware = {"storage_unavailable": True}
            if report.get("kind") not in {"search", "comparison"}:
                try:
                    hardware = RunnerClient(timeout=8).hardware()
                except (RunnerError, RunnerUnavailable):
                    pass
            check()
            storage = storage_info(hardware) if report.get("kind") not in {"search", "comparison"} else None
            for index, file in enumerate(report["files"]):
                if index % 16 == 0:
                    check()
                candidates = None
                if report.get("kind") == "install_plan":
                    from app.hub_candidates import download_candidate

                    candidates = (download_candidate(report["candidate"]),)
                if candidates:
                    file["assessment"] = assess_file(file, hardware, storage, candidates=candidates)
                else:
                    from app.model_variant_advice import assess_variant

                    file["assessment"] = assess_variant(file, report, hardware, storage)
            if report.get("kind") not in {"search", "comparison"}:
                from app.model_variant_advice import rank_variants

                rank_variants(report, context_target=report.get("context_target", 32768))
            report.update(
                observed_at=utcnow().isoformat(),
                hardware_observed=report.get("hardware_observed", False)
                if report.get("kind") == "comparison"
                else not hardware.get("storage_unavailable", False),
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
                f"Compared {len(report['items'])} repositories against this station; no weights downloaded."
                if report.get("kind") == "comparison"
                else f"Inspected {report['repository']}: {len(report['files'])} weight files; no weights downloaded."
                if "repository" in report
                else f"Found {len(report['items'])} model repositories; review compatibility before installing."
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            session.commit()
        except (InspectionStopped, InspectionClaimLost):
            session.rollback()
        return "done"
