"""Reviewed new-model plans feed the existing owned downloader and registry."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import session_scope
from app.hub_candidates import download_candidate
from app.model_hub import enqueue_inspection
from app.model_setup import INTENT, administrator, attempt, fingerprint, view
from app.models import Run, Task

router = APIRouter(prefix="/api/model-hub", tags=["model discovery"])
DB = Annotated[Session, Depends(session_scope)]


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    inspection_run_id: UUID
    observation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    filename: str = Field(min_length=1, max_length=400)
    context_target: Literal[32768, 131072] = 32768


def source_observation(session, identity, expected):
    run = session.get(Run, str(identity))
    if run is None or run.executor_type != "model_hub_inspect" or run.status != "succeeded":
        raise HTTPException(404, "Completed model-source inspection not found")
    report = run.metadata_json.get("source_inspection")
    if not isinstance(report, dict) or report.get("kind") in {"search", "install_plan"}:
        raise HTTPException(409, "Choose a completed repository or file inspection")
    actual = fingerprint({k: v for k, v in report.items() if k != "observation_sha256"})
    if expected != report.get("observation_sha256") or actual != expected:
        raise HTTPException(409, "The source observation changed; inspect and review it again")
    return report


@router.post("/plans", status_code=202)
def plan(body: PlanRequest, session: DB):
    administrator(session)
    report = source_observation(session, body.inspection_run_id, body.observation_sha256)
    if not any(file.get("filename") == body.filename for file in report.get("files", [])):
        raise HTTPException(422, "Choose a file from the inspected immutable revision")
    return enqueue_inspection(
        session,
        body.client_request_id,
        {
            "planning": {
                "inspection_run_id": str(body.inspection_run_id),
                "observation_sha256": body.observation_sha256,
                "filename": body.filename,
                "context_target": body.context_target,
            }
        },
    )


class InstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    plan_run_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license_accepted: StrictBool
    workload_accepted: StrictBool = False


@router.post("/downloads", status_code=202)
def install(body: InstallRequest, session: DB):
    administrator(session)
    if not body.license_accepted:
        raise HTTPException(422, "Review the source and license before accepting this model download")
    source = session.get(Run, str(body.plan_run_id))
    if source is None or source.status != "succeeded" or source.executor_type != "model_hub_inspect":
        raise HTTPException(404, "Completed installation plan not found")
    report = source.metadata_json.get("source_inspection", {})
    if report.get("kind") != "install_plan":
        raise HTTPException(409, "Review a complete model installation plan first")
    candidate = download_candidate(report["candidate"])
    snapshot = candidate.model_dump(mode="json")
    if candidate.capability in {"image", "video", "speech"} and not candidate.preparation_available:
        raise HTTPException(
            409,
            candidate.preparation_notice
            or "Prepare the supported media runtime prerequisites before installing this checkpoint",
        )
    if candidate.capability == "video" and not body.workload_accepted:
        raise HTTPException(422, "Review and accept the fixed video workload and explicit CPU offload")
    if fingerprint(snapshot) != body.manifest_sha256 or report.get("manifest_sha256") != body.manifest_sha256:
        raise HTTPException(409, "The model manifest changed; review its source, hardware and license again")
    prior = session.get(Task, str(body.client_request_id))
    if prior is not None:
        saved = prior.metadata_json.get("model_download", {})
        if (
            prior.intent != INTENT
            or saved.get("source_plan_run_id") != str(body.plan_run_id)
            or saved.get("manifest_sha256") != body.manifest_sha256
        ):
            raise HTTPException(409, "This request ID belongs to another model download")
        return view(session, prior)
    if (
        not report.get("files")
        or report["files"][0].get("assessment", {}).get("hardware_status") != "estimated_fit"
    ):
        raise HTTPException(409, "This plan has no fitted GPU profile; review the model or hardware first")
    if report["files"][0]["assessment"]["disk"]["status"] != "file_fits":
        raise HTTPException(409, "Confirm sufficient application storage in a new hardware plan")
    saved = {
        "catalog_id": candidate.id,
        "manifest_sha256": body.manifest_sha256,
        "entry": snapshot,
        "license_accepted": True,
        **({"workload_accepted": True} if candidate.capability == "video" else {}),
        "download_only": False,
        "attempt": 1,
        "receipts": {},
        "source_plan_run_id": source.id,
    }
    task = Task(
        id=str(body.client_request_id),
        title="Prepare " + candidate.name,
        prompt="Download and verify the explicitly reviewed new model",
        capability="models.download",
        intent=INTENT,
        metadata_json={},
    )
    try:
        session.add(task)
        session.flush()
        attempt(session, task, saved)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "This download request was submitted concurrently; retry its ID") from exc
    return view(session, task)
