"""Owned durable catalog download tasks around existing Runs and shared models."""

import hashlib
import json
import math
import shutil
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.account_profile import accounts_enabled
from app.config import get_settings
from app.db import session_scope, utcnow
from app.models import ModelDefinition, ModelFile, Run, Task
from app.runs import create_run, run_dict
from app.setup_models import CANDIDATES, STARTER_CANDIDATE_IDS, candidate
from app.state import TERMINAL
from app.task_control import cancel_task, lock_task

router = APIRouter(prefix="/api/setup", tags=["guided model setup"])
DB = Annotated[Session, Depends(session_scope)]
INTENT = "model.catalog.download"
PERMISSIONS = ["filesystem_read", "workspace_write", "network_read", "manage_models"]


def administrator(session):
    scope = getattr(session, "scope", None)
    if accounts_enabled() and (scope is None or not scope.administrator or scope.read_only):
        raise HTTPException(403, "Model setup requires an administrator")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def storage_info():
    # Inspect the actual application volume, not an unrelated host model root.
    try:
        usage = shutil.disk_usage(get_settings().data_dir)
        return {"free_bytes": usage.free, "total_bytes": usage.total, "headroom_bytes": 256 * 1024**2}
    except OSError:
        return None


def recommendation(entry, hardware):
    from app.llama import fit_coding_context, kv_budget_mib

    if entry.runtime_profile:
        from app.cpu_models import estimate

        ram = (hardware.get("memory") or {}).get("total_mib")
        needed = estimate(entry)
        fits = type(ram) in {int, float} and math.isfinite(ram) and ram >= needed + 2048
        return {
            "fits": fits,
            "reason": "Runs on CPU; slower, with a reserved system-RAM budget"
            if fits
            else "Connect the Host Runner to inspect system RAM"
            if type(ram) not in {int, float} or not math.isfinite(ram)
            else "More system RAM is needed for this CPU profile",
            "gpus": [],
            "context_size": 4096 if fits else None,
            "cache_type": "q8_0",
            "ram_mib": needed,
            "runtime_profile": entry.runtime_profile,
        }
    devices = [
        g
        for g in (hardware.get("gpus") or [])
        if isinstance(g, dict)
        and type(g.get("index")) is int
        and type(g.get("memory_total_mib")) in {int, float}
        and math.isfinite(g["memory_total_mib"])
        and 0 < g["memory_total_mib"] < 1048576
    ]
    devices.sort(key=lambda g: (-g["memory_total_mib"], g["index"]))
    memory = (hardware.get("memory") or {}).get("total_mib")
    if type(memory) not in {int, float} or not math.isfinite(memory):
        return {
            "fits": False,
            "reason": "Connect the Host Runner to inspect available hardware",
            "gpus": [],
            "context_size": None,
        }
    if memory < entry.file.size_bytes / 1024**2 + 2048:
        return {
            "fits": False,
            "reason": "More system RAM is needed for this model",
            "gpus": [],
            "context_size": None,
        }
    # Q8_0 KV cache geometry declared by the pinned model configuration. The
    # actual downloaded GGUF and native load admission remain authoritative.
    per_token = (
        entry.attention_layers
        * entry.kv_heads
        * ((entry.key_length + 31) // 32 + (entry.value_length + 31) // 32)
        * 34
    )
    best = None
    for count in range(1, len(devices) + 1):
        group = devices[:count]
        budget = kv_budget_mib(
            [g["memory_total_mib"] for g in group], entry.file.size_bytes, entry.state_reserve_mib
        )
        if budget * 1024**2 < 4096 * per_token:
            continue
        indices = [g["index"] for g in group]
        context = fit_coding_context(
            gpus=indices,
            size_bytes=entry.file.size_bytes,
            gpu_memory_mib=[g["memory_total_mib"] for g in group],
            ceiling=entry.context_ceiling,
            context_profile={
                "trained_context": entry.trained_context,
                "q8_kv_bytes_per_token": per_token,
                "state_reserve_mib": entry.state_reserve_mib,
            },
        )
        result = {
            "fits": True,
            "reason": "Estimated GPU fit with memory headroom; verified again when loading",
            "gpus": indices,
            "context_size": context,
            "cache_type": "q8_0",
        }
        if best is None or context > best["context_size"]:
            best = result
        # Preserve legacy presets; long-context profiles may need a GPU pair
        # even when the weights alone fit one device with a very short cache.
        if entry.context_ceiling <= 32768 or context >= entry.context_ceiling:
            return result
    if best is not None:
        return best
    return {
        "fits": False,
        "reason": "No detected GPU group fits this managed CUDA profile; existing local servers remain usable",
        "gpus": [],
        "context_size": None,
    }


def view(session, task):
    saved = task.metadata_json["model_download"]
    run = session.get(Run, saved["run_id"])
    return {
        "id": task.id,
        "catalog_id": saved["catalog_id"],
        "manifest_sha256": saved["manifest_sha256"],
        "entry": saved["entry"],
        "attempt": saved["attempt"],
        "run": run_dict(run),
        "progress": run.metadata_json.get("model_download", {}),
        "model_file_id": run.metadata_json.get("model_file_id"),
        "model_key": "llamacpp:" + run.metadata_json["model_file_id"]
        if run.metadata_json.get("model_file_id")
        else None,
        "resume_allowed": run.status in {"failed", "interrupted", "canceled"},
    }


def get_task(session, identity):
    task = session.get(Task, str(identity))
    if task is None or task.intent != INTENT or not task.metadata_json.get("model_download"):
        raise HTTPException(404, "Model preparation was not found")
    return task


@router.get("/catalog")
def catalog(session: DB):
    from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable

    try:
        hardware = RunnerClient(timeout=10).hardware()
    except (RunnerError, RunnerUnavailable):
        hardware = {}
    scope = getattr(session, "scope", None)
    can_prepare = not accounts_enabled() or bool(scope and scope.administrator and not scope.read_only)
    entries = []
    for item in CANDIDATES:
        installed = session.scalar(
            select(ModelFile).where(
                ModelFile.relative_path == "models/store/" + item.file.sha256,
                ModelFile.availability == "present",
            )
        )
        preset = recommendation(item, hardware)
        definition = (
            session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == installed.id))
            if installed
            else None
        )
        entries.append(
            {
                **item.model_dump(mode="json"),
                "starter": bool(item.runtime_profile)
                if not hardware.get("gpus")
                else item.id in STARTER_CANDIDATE_IDS,
                "manifest_sha256": fingerprint(item.model_dump(mode="json")),
                "recommendation": preset,
                "ready_to_try": bool(
                    installed
                    and definition
                    and definition.status == "registered"
                    and preset["fits"]
                    and (definition.metadata_json or {}).get("runtime_profile") == item.runtime_profile
                ),
                "model_file_id": installed.id if installed else None,
                "definition_id": definition.id if definition else None,
            }
        )
    return {
        "can_prepare": can_prepare,
        "entries": entries,
        "hardware": {"memory": hardware.get("memory"), "gpus": hardware.get("gpus", [])},
        "storage": storage_info(),
        "scope": "These are downloadable conversation models; other capability/runtime setup follows its own qualified recipes.",
    }


class Download(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    catalog_id: str = Field(min_length=1, max_length=80)
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license_accepted: StrictBool
    download_only: StrictBool = False


class Resume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    expected_run_id: UUID


def attempt(session, task, saved, *, previous=None):
    run = create_run(
        session,
        task,
        run_type="model",
        capability="models.download",
        executor_type="model_download",
        execution_target="container",
        operation_key=f"model-download:{saved['attempt']}",
        parameters={
            "entry": saved["entry"],
            "manifest_sha256": saved["manifest_sha256"],
            "download_only": saved.get("download_only", False),
            "execution_deadline_at": (utcnow() + timedelta(hours=24)).isoformat(),
        },
        permissions=PERMISSIONS,
        requested_resources={"ram_mib": 256},
        retry_class="inspect",
        parent_run_id=previous.id if previous else None,
    )
    task.metadata_json = {**task.metadata_json, "model_download": {**saved, "run_id": run.id}}
    return run


@router.post("/downloads", status_code=202)
def download(body: Download, session: DB):
    administrator(session)
    if not body.license_accepted:
        raise HTTPException(422, "Review and accept this model's license before downloading")
    prior = session.get(Task, str(body.client_request_id))
    if prior is not None:
        saved = prior.metadata_json.get("model_download") or {}
        if (
            prior.intent != INTENT
            or saved.get("catalog_id") != body.catalog_id
            or saved.get("manifest_sha256") != body.manifest_sha256
            or bool(saved.get("download_only", False)) != body.download_only
        ):
            raise HTTPException(409, "This submission ID belongs to a different request")
        return view(session, prior)
    item = candidate(body.catalog_id)
    if item is None or fingerprint(item.model_dump(mode="json")) != body.manifest_sha256:
        raise HTTPException(409, "The model catalog changed. Refresh and review its download/license details")
    saved = {
        "catalog_id": item.id,
        "manifest_sha256": body.manifest_sha256,
        "entry": item.model_dump(mode="json"),
        "license_accepted": True,
        "download_only": body.download_only,
        "attempt": 1,
        "receipts": {},
    }
    task = Task(
        id=str(body.client_request_id),
        title="Prepare " + item.name,
        prompt="Download and verify the explicitly selected catalog model",
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
        raise HTTPException(409, "This model submission ID is already in use") from exc
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
    return view(session, get_task(session, identity))


@router.post("/downloads/{identity}/cancel")
def cancel(identity: UUID, session: DB):
    administrator(session)
    task = get_task(session, identity)
    cancel_task(session, task)
    session.commit()
    return view(session, task)


@router.post("/downloads/{identity}/resume", status_code=202)
def resume(identity: UUID, body: Resume, session: DB):
    administrator(session)
    task = get_task(session, identity)
    lock_task(session, task)
    saved = task.metadata_json["model_download"]
    receipts = saved.get("receipts", {})
    receipt = receipts.get(str(body.client_request_id))
    if receipt:
        if receipt["expected_run_id"] != str(body.expected_run_id):
            raise HTTPException(409, "Resume ID belongs to a different attempt")
        return view(session, task)
    previous = session.get(Run, saved["run_id"])
    if (
        previous.id != str(body.expected_run_id)
        or previous.status not in TERMINAL
        or previous.status == "succeeded"
    ):
        raise HTTPException(409, "Inspect the current model preparation before resuming")
    if saved["attempt"] >= 100:
        raise HTTPException(409, "This preparation has reached its retry bound; start a new reviewed request")
    task.metadata_json = {
        key: value for key, value in task.metadata_json.items() if key != "stop_requested_at"
    }
    if len(receipts) >= 100:
        raise HTTPException(409, "The model preparation receipt bound was reached")
    receipts = {**receipts, str(body.client_request_id): {"expected_run_id": previous.id}}
    attempt(
        session, task, {**saved, "attempt": saved["attempt"] + 1, "receipts": receipts}, previous=previous
    )
    session.commit()
    return view(session, task)
