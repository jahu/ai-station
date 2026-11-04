"""Owned multi-file model preparation; runtime installation is a later operation."""

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.account_profile import accounts_enabled
from app.db import session_scope, utcnow
from app.model_bundles import BUNDLES, bundle
from app.model_setup import PERMISSIONS, Resume, administrator, fingerprint, storage_info
from app.models import ModelFile, Run, Task
from app.runs import create_run, run_dict
from app.state import TERMINAL
from app.task_control import cancel_task, lock_task

router = APIRouter(prefix="/api/setup/bundles", tags=["model bundle files"])
DB = Annotated[Session, Depends(session_scope)]
INTENT = "model.bundle.download"


def view(session, task):
    saved = task.metadata_json["bundle_download"]
    run = session.get(Run, saved["run_id"])
    return {
        "id": task.id,
        "catalog_id": saved["catalog_id"],
        "manifest_sha256": saved["manifest_sha256"],
        "entry": saved["entry"],
        "attempt": saved["attempt"],
        "run": run_dict(run),
        "progress": run.metadata_json.get("model_download", {}),
        "model_file_ids": run.metadata_json.get("model_file_ids", []),
        "runtime_prepared": False,
        "ready_to_try": False,
        "resume_allowed": run.status in {"failed", "interrupted", "canceled"},
    }


def task_for(session, identity):
    task = session.get(Task, str(identity))
    if task is None or task.intent != INTENT or not task.metadata_json.get("bundle_download"):
        raise HTTPException(404, "Model bundle preparation was not found")
    return task


@router.get("/catalog")
def catalog(session: DB):
    scope = getattr(session, "scope", None)
    return {
        "can_prepare": not accounts_enabled() or bool(scope and scope.administrator and not scope.read_only),
        "storage": storage_info(),
        "bundles": [
            {
                **item.model_dump(mode="json"),
                "manifest_sha256": fingerprint(item.model_dump(mode="json")),
                "size_bytes": item.size_bytes,
                "model_file_ids": list(
                    session.scalars(
                        select(ModelFile.id).where(
                            ModelFile.relative_path.in_(
                                "models/store/" + entry.file.sha256 for entry in item.files
                            ),
                            ModelFile.availability == "present",
                        )
                    )
                ),
                "runtime_prepared": False,
                "ready_to_try": False,
            }
            for item in BUNDLES
        ],
        "scope": "Prepare all reviewed companion files; a qualified speech runtime is still required for generation.",
    }


class Download(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    catalog_id: str = Field(min_length=1, max_length=80)
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license_accepted: StrictBool


def attempt(session, task, saved, *, previous=None):
    run = create_run(
        session,
        task,
        run_type="model",
        capability="models.download",
        executor_type="model_bundle_download",
        execution_target="container",
        operation_key=f"bundle-download:{saved['attempt']}",
        parameters={
            "entry": saved["entry"],
            "manifest_sha256": saved["manifest_sha256"],
            "execution_deadline_at": (utcnow() + timedelta(hours=24)).isoformat(),
        },
        permissions=PERMISSIONS,
        requested_resources={"ram_mib": 256},
        retry_class="inspect",
        parent_run_id=previous.id if previous else None,
    )
    task.metadata_json = {**task.metadata_json, "bundle_download": {**saved, "run_id": run.id}}
    return run


@router.post("/downloads", status_code=202)
def download(body: Download, session: DB):
    administrator(session)
    if not body.license_accepted:
        raise HTTPException(422, "Review and accept this model bundle's license before downloading")
    prior = session.get(Task, str(body.client_request_id))
    if prior is not None:
        saved = prior.metadata_json.get("bundle_download") or {}
        if prior.intent != INTENT or any(
            saved.get(key) != getattr(body, key) for key in ("catalog_id", "manifest_sha256")
        ):
            raise HTTPException(409, "This submission ID belongs to a different request")
        return view(session, prior)
    item = bundle(body.catalog_id)
    if item is None or fingerprint(item.model_dump(mode="json")) != body.manifest_sha256:
        raise HTTPException(409, "The bundle catalog changed. Refresh and review its files and license")
    saved = {
        "catalog_id": item.id,
        "manifest_sha256": body.manifest_sha256,
        "entry": item.model_dump(mode="json"),
        "license_accepted": True,
        "attempt": 1,
        "receipts": {},
    }
    task = Task(
        id=str(body.client_request_id),
        title="Prepare " + item.name,
        prompt="Download and verify all explicitly reviewed companion model files",
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
        raise HTTPException(409, "This bundle submission ID is already in use") from exc
    return view(session, task)


@router.get("/downloads")
def downloads(session: DB, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    return [
        view(session, row)
        for row in session.scalars(
            select(Task)
            .where(Task.intent == INTENT)
            .order_by(Task.created_at.desc(), Task.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ]


@router.get("/downloads/{identity}")
def detail(identity: UUID, session: DB):
    return view(session, task_for(session, identity))


@router.post("/downloads/{identity}/cancel")
def cancel(identity: UUID, session: DB):
    administrator(session)
    task = task_for(session, identity)
    cancel_task(session, task)
    session.commit()
    return view(session, task)


@router.post("/downloads/{identity}/resume", status_code=202)
def resume(identity: UUID, body: Resume, session: DB):
    administrator(session)
    task = task_for(session, identity)
    lock_task(session, task)
    saved = task.metadata_json["bundle_download"]
    receipts = saved.get("receipts", {})
    if receipt := receipts.get(str(body.client_request_id)):
        if receipt["expected_run_id"] != str(body.expected_run_id):
            raise HTTPException(409, "Resume ID belongs to a different attempt")
        return view(session, task)
    previous = session.get(Run, saved["run_id"])
    if (
        previous.id != str(body.expected_run_id)
        or previous.status not in TERMINAL
        or previous.status == "succeeded"
    ):
        raise HTTPException(409, "Inspect the current bundle preparation before resuming")
    if saved["attempt"] >= 100 or len(receipts) >= 100:
        raise HTTPException(409, "This preparation reached its retry bound; start a new reviewed request")
    task.metadata_json = {
        key: value for key, value in task.metadata_json.items() if key != "stop_requested_at"
    }
    attempt(
        session,
        task,
        {
            **saved,
            "attempt": saved["attempt"] + 1,
            "receipts": {**receipts, str(body.client_request_id): {"expected_run_id": previous.id}},
        },
        previous=previous,
    )
    session.commit()
    return view(session, task)
