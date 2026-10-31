"""Owned runtime preparation Tasks; shared image facts never share private Runs."""

from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import utcnow
from app.image_setup_client import ImageSetupClient
from app.model_setup import DB, Resume, administrator, fingerprint
from app.models import Run, Task
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, run_dict
from app.speech_setup_client import SpeechSetupClient
from app.task_control import cancel_task, lock_task

router = APIRouter(prefix="/api/setup/runtimes", tags=["guided runtime setup"])
INTENT = "runtime.catalog.prepare"
PERMISSIONS = ["manage_models", "network_read", "workspace_write"]
SPEECH_PROFILE = "chatterbox-v3-linux-x86-64-python312-v1"
IMAGE_PROFILE = "qwen-image21-cuda-linux-amd64-v1"
Profile = Literal[
    "llamacpp-cuda-linux-amd64-v1",
    "chatterbox-v3-linux-x86-64-python312-v1",
    "qwen-image21-cuda-linux-amd64-v1",
]


class Prepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    profile: Profile
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license_accepted: StrictBool


def report(profile="llamacpp-cuda-linux-amd64-v1"):
    try:
        client = (
            ImageSetupClient(timeout=30)
            if profile == IMAGE_PROFILE
            else SpeechSetupClient(timeout=30)
            if profile == SPEECH_PROFILE
            else RunnerClient(timeout=30)
        )
        return client.runtime_setup_catalog()
    except (RunnerError, RunnerUnavailable):
        return {
            "installation_available": False,
            "installation_notice": "Connect the Host Runner to inspect local runtime setup",
            "image": {"status": "unknown", "present": False},
        }


@router.get("")
def catalog(session: DB, profile: Profile = "llamacpp-cuda-linux-amd64-v1"):
    from app.account_profile import accounts_enabled

    scope = getattr(session, "scope", None)
    can_prepare = not accounts_enabled() or bool(scope and scope.administrator and not scope.read_only)
    return {**report(profile), "can_prepare": can_prepare}


def view(session, task):
    saved = task.metadata_json["runtime_preparation"]
    run = session.get(Run, saved["run_id"])
    return {
        "id": task.id,
        "recipe": saved["recipe"],
        "manifest_sha256": saved["manifest_sha256"],
        "attempt": saved["attempt"],
        "run": run_dict(run),
        "progress": run.metadata_json.get("runtime_preparation", {}),
        "resume_allowed": run.status in {"failed", "interrupted", "canceled"}
        and not run.metadata_json.get("cleanup_requires_inspection"),
    }


def get_task(session, identity):
    task = session.get(Task, str(identity))
    if task is None or task.intent != INTENT or not task.metadata_json.get("runtime_preparation"):
        raise HTTPException(404, "Runtime preparation was not found")
    return task


def attempt(session, task, saved, previous=None):
    speech = saved["recipe"]["profile"] == SPEECH_PROFILE
    image = saved["recipe"]["profile"] == IMAGE_PROFILE
    inputs = speech or image
    run = create_run(
        session,
        task,
        run_type="runtime",
        capability="runtime.prepare",
        executor_type="image_setup" if image else "speech_setup" if speech else "runtime_setup",
        execution_target="host",
        operation_key=f"runtime-prepare:{saved['attempt']}",
        parameters={
            "profile": saved["recipe"]["profile"],
            "manifest_sha256": saved["manifest_sha256"],
            "recipe": saved["recipe"],
            "execution_deadline_at": (utcnow() + timedelta(hours=24 if inputs else 2)).isoformat(),
        },
        permissions=[*PERMISSIONS, "filesystem_read"] if inputs else PERMISSIONS,
        requested_resources={"ram_mib": 4096 if inputs else 1024},
        retry_class="inspect",
        parent_run_id=previous.id if previous else None,
    )
    task.metadata_json = {**task.metadata_json, "runtime_preparation": {**saved, "run_id": run.id}}


@router.post("", status_code=202)
def prepare(body: Prepare, session: DB):
    administrator(session)
    if not body.license_accepted:
        raise HTTPException(422, "Review the runtime and bundled component licenses before preparing")
    existing = session.get(Task, str(body.client_request_id))
    if existing is not None:
        saved = existing.metadata_json.get("runtime_preparation") or {}
        if (
            existing.intent != INTENT
            or saved.get("manifest_sha256") != body.manifest_sha256
            or saved.get("recipe", {}).get("profile") != body.profile
        ):
            raise HTTPException(409, "This submission ID belongs to a different request")
        return view(session, existing)
    observed = report(body.profile)
    recipe = observed.get("recipe") or {}
    if not observed.get("installation_available"):
        raise HTTPException(
            409, observed.get("installation_notice") or "Runtime preparation is not available"
        )
    if (
        recipe.get("profile") != body.profile
        or fingerprint(recipe) != body.manifest_sha256
        or observed.get("manifest_sha256") != body.manifest_sha256
    ):
        raise HTTPException(409, "The runtime recipe changed; refresh and review it")
    task = Task(
        id=str(body.client_request_id),
        title="Prepare " + recipe.get("name", "Chatterbox speech"),
        prompt="Prepare the explicitly reviewed local runtime",
        capability="runtime.prepare",
        intent=INTENT,
        metadata_json={},
    )
    try:
        session.add(task)
        session.flush()
        attempt(
            session,
            task,
            {
                "recipe": recipe,
                "manifest_sha256": body.manifest_sha256,
                "license_accepted": True,
                "attempt": 1,
                "receipts": {},
            },
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Runtime submission ID is already in use") from exc
    return view(session, task)


@router.get("/preparations")
def preparations(
    session: DB,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    profile: Profile = "llamacpp-cuda-linux-amd64-v1",
):
    return [
        view(session, task)
        for task in session.scalars(
            select(Task)
            .where(
                Task.intent == INTENT,
                Task.metadata_json["runtime_preparation"]["recipe"]["profile"].as_string() == profile,
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ]


@router.get("/preparations/{identity}")
def detail(identity: UUID, session: DB):
    return view(session, get_task(session, identity))


@router.post("/preparations/{identity}/cancel")
def cancel(identity: UUID, session: DB):
    administrator(session)
    task = get_task(session, identity)
    cancel_task(session, task)
    session.commit()
    return view(session, task)


@router.post("/preparations/{identity}/resume", status_code=202)
def resume(identity: UUID, body: Resume, session: DB):
    administrator(session)
    task = get_task(session, identity)
    lock_task(session, task)
    saved = task.metadata_json["runtime_preparation"]
    receipts = saved.get("receipts", {})
    receipt = receipts.get(str(body.client_request_id))
    if receipt:
        if receipt["expected_run_id"] != str(body.expected_run_id):
            raise HTTPException(409, "Resume ID belongs to a different attempt")
        return view(session, task)
    previous = session.get(Run, saved["run_id"])
    if previous.id != str(body.expected_run_id) or not view(session, task)["resume_allowed"]:
        raise HTTPException(409, "Inspect the current runtime preparation before resuming")
    if saved["attempt"] >= 100:
        raise HTTPException(409, "The runtime retry bound was reached; start a new reviewed request")
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
        previous,
    )
    session.commit()
    return view(session, task)
