"""Model selection and durable ownership of llama.cpp runtime lifecycle."""

import json
import re
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.events import append_event
from app.models import ModelDefinition, ModelFile, ResourceLock, Run, RuntimeInstance, Task
from app.permissions import require
from app.resources import active_locks, release_run_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.serialize import runtime_dict
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/llama")
DB = Annotated[Session, Depends(session_scope)]


CODING_CONTEXT_CEILING = 131072
CODING_CONTEXT_FLOOR = 4096
CODING_CONTEXT_FALLBACK = 16384
_VRAM_USABLE_FRACTION = 0.85
_CUDA_OVERHEAD_MIB_PER_GPU = 768


class LoadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_file_id: UUID
    gpus: list[Annotated[int, Field(ge=0)]] = Field(max_length=16)
    context_size: int = Field(default=4096, ge=512, le=262144, multiple_of=256)
    cache_type: Literal["f16", "q8_0"] = "f16"
    projector_file_id: UUID | None = None


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def q8_kv_bytes_per_token(size_bytes: int) -> int:
    """Conservative Q8 KV bytes/token from GGUF size; 27–32B GQA is much hungrier than 7B."""
    gib = max(0.0, size_bytes) / (1024**3)
    return int(max(24.0, min(160.0, 8 + 7.5 * gib)) * 1024)


def fit_coding_context(
    *,
    gpus: list[int],
    size_bytes: int,
    gpu_memory_mib: list[float] | None = None,
    ceiling: int = CODING_CONTEXT_CEILING,
    failed_sizes: list[int] | tuple[int, ...] = (),
    proven_success: int | None = None,
    context_profile: dict | None = None,
) -> int:
    """Largest GPU-resident Q8 context. 131072 is a ceiling, never a default load size."""
    limit = min(CODING_CONTEXT_CEILING, max(CODING_CONTEXT_FLOOR, (int(ceiling) // 256) * 256))
    if context_profile:
        limit = min(limit, context_profile["trained_context"] // 256 * 256)
    failed = {max(CODING_CONTEXT_FLOOR, (int(size) // 256) * 256) for size in failed_sizes if size}
    if not gpus:
        return min(limit, CODING_CONTEXT_FLOOR)
    missing_vram = (
        gpu_memory_mib is None
        or len(gpu_memory_mib) != len(gpus)
        or any(value is None for value in gpu_memory_mib)
    )
    if missing_vram:
        computed = proven_success or CODING_CONTEXT_FALLBACK
    else:
        kv_mib = (
            _VRAM_USABLE_FRACTION * sum(float(value) for value in gpu_memory_mib)
            - size_bytes / (1024 * 1024)
            - _CUDA_OVERHEAD_MIB_PER_GPU * len(gpus)
            - (context_profile or {}).get("state_reserve_mib", 0)
        )
        if kv_mib <= 0:
            computed = CODING_CONTEXT_FLOOR
        else:
            per_token = (context_profile or {}).get("q8_kv_bytes_per_token") or q8_kv_bytes_per_token(
                size_bytes
            )
            computed = int((kv_mib * 1024 * 1024) / per_token)
        if proven_success:
            computed = max(computed, proven_success)
    computed = min(limit, max(CODING_CONTEXT_FLOOR, (int(computed) // 256) * 256))
    if failed:
        # A changed estimate must not jump above an already-failed allocation.
        computed = min(computed, max(CODING_CONTEXT_FLOOR, min(failed) // 2 // 256 * 256))
    while computed in failed and computed > CODING_CONTEXT_FLOOR:
        halved = (computed // 2 // 256) * 256
        computed = CODING_CONTEXT_FLOOR if halved < CODING_CONTEXT_FLOOR else halved
    return computed


def gpu_memory_totals(gpus: list[int]) -> list[float] | None:
    if not gpus:
        return []
    try:
        hardware = RunnerClient().hardware()
    except Exception:
        return None
    by_index = {}
    for gpu in hardware.get("gpus") or []:
        try:
            by_index[int(gpu["index"])] = gpu.get("memory_total_mib")
        except (TypeError, ValueError, KeyError):
            continue
    totals = []
    for index in gpus:
        value = by_index.get(index)
        if value is None:
            return None
        try:
            totals.append(float(value))
        except (TypeError, ValueError):
            return None
    return totals


def _q8_history(session, model_file_id, gpus):
    for instance in instances(session):
        meta = instance.metadata_json or {}
        if (
            meta.get("model_file_id") == model_file_id
            and list(meta.get("gpus") or []) == list(gpus)
            and meta.get("cache_type", "f16") == "q8_0"
        ):
            yield instance


def failed_context_sizes(session, model_file_id, gpus) -> list[int]:
    sizes = []
    for instance in _q8_history(session, model_file_id, gpus):
        if instance.metadata_json.get("context_fit") != "too_large":
            continue
        raw = instance.metadata_json.get("failed_context_size") or instance.metadata_json.get("context_size")
        try:
            size = int(raw)
        except (TypeError, ValueError):
            continue
        if size:
            sizes.append(size)
    return sizes


def proven_context_size(session, model_file_id, gpus) -> int | None:
    best = None
    for instance in _q8_history(session, model_file_id, gpus):
        if (
            instance.status not in {"ready", "stopped"}
            or instance.metadata_json.get("context_fit") == "too_large"
        ):
            continue
        try:
            size = int(instance.metadata_json.get("context_size") or 0)
        except (TypeError, ValueError):
            continue
        if size:
            best = size if best is None else max(best, size)
    return best


def coding_context_target(session, model, gpus, *, ceiling=CODING_CONTEXT_CEILING) -> int:
    profile = next(
        (
            item.metadata_json["context_profile"]
            for item in _q8_history(session, model.id, gpus)
            if item.metadata_json.get("context_profile")
            and item.metadata_json.get("model_size_bytes") == model.size_bytes
            and item.metadata_json.get("model_mtime") == model.mtime
        ),
        None,
    )
    return fit_coding_context(
        gpus=gpus,
        size_bytes=model.size_bytes,
        gpu_memory_mib=gpu_memory_totals(gpus),
        ceiling=ceiling,
        failed_sizes=failed_context_sizes(session, model.id, gpus),
        proven_success=proven_context_size(session, model.id, gpus),
        context_profile=profile,
    )


def instances(session):
    return list(
        session.scalars(
            select(RuntimeInstance).where(
                RuntimeInstance.runtime_key == "llama.cpp", RuntimeInstance.ownership == "managed"
            )
        )
    )


def loadable_model(row):
    return bool(
        row
        and row.category == "llm"
        and row.format == "gguf"
        and row.availability == "present"
        and not re.search(r"(^|[-_.])mmproj([-_.]|$)", row.filename, re.IGNORECASE)
    )


def vision_projector(session, model, companions=None):
    """Only an unambiguous installed companion in the same discovered folder."""
    matches = [
        row
        for row in (
            companions
            if companions is not None
            else session.scalars(
                select(ModelFile).where(
                    ModelFile.format == "gguf",
                    ModelFile.availability == "present",
                    ModelFile.filename.ilike("mmproj%"),
                )
            )
        )
        if row.filename.lower().startswith("mmproj")
        and PurePosixPath(row.host_path).parent == PurePosixPath(model.host_path).parent
    ]
    return matches[0] if len(matches) == 1 else None


@router.get("")
def catalog(session: DB):
    companions = list(
        session.scalars(
            select(ModelFile).where(
                ModelFile.format == "gguf",
                ModelFile.availability == "present",
                ModelFile.filename.ilike("mmproj%"),
            )
        )
    )
    return {
        "models": [
            {
                "id": row.id,
                "name": f"{PurePosixPath(row.host_path).parent.name} · {row.filename}",
                "size_bytes": row.size_bytes,
                "model_key": "llamacpp:" + row.id,
                "vision_available": vision_projector(session, row, companions) is not None,
            }
            for row in session.scalars(
                select(ModelFile)
                .where(
                    ModelFile.category == "llm",
                    ModelFile.format == "gguf",
                    ModelFile.availability == "present",
                )
                .order_by(ModelFile.filename)
                .limit(200)
            )
            if loadable_model(row)
        ],
        "instances": [runtime_dict(row) for row in instances(session)],
    }


@router.post("/load", status_code=202)
def load(body: LoadModel, session: DB):
    run = enqueue_load(body, session)
    session.commit()
    return run_dict(run)


def enqueue_load(body, session, *, task=None, allow_stopping=False, _fitted_context=False):
    model = session.get(ModelFile, str(body.model_file_id))
    if not loadable_model(model):
        raise HTTPException(422, "Choose a present language-model GGUF; mmproj files are vision companions")
    if len(set(body.gpus)) != len(body.gpus):
        raise HTTPException(422, "Choose distinct GPUs")
    requested_context = body.context_size
    projector = None
    if body.projector_file_id is not None:
        companion = vision_projector(session, model)
        if companion is None or companion.id != str(body.projector_file_id):
            raise HTTPException(422, "Choose this model's unique installed vision companion")
        projector = {
            "path": companion.host_path,
            "size_bytes": companion.size_bytes,
            "mtime": companion.mtime,
        }
    if body.cache_type == "q8_0" and not _fitted_context:
        body = body.model_copy(
            update={
                "context_size": coding_context_target(session, model, body.gpus, ceiling=body.context_size)
            }
        )
    for instance in instances(session):
        if instance.metadata_json.get("model_file_id") == model.id and instance.status not in {
            "stopped",
            "failed",
            *(["stopping"] if allow_stopping else []),
        }:
            raise HTTPException(409, "This model already has a runtime; inspect it before loading again")
    instance = RuntimeInstance(
        id=str(uuid4()),
        runtime_key="llama.cpp",
        name=model.filename,
        ownership="managed",
        status="queued",
        metadata_json={
            "model_file_id": model.id,
            "gpus": body.gpus,
            "context_size": body.context_size,
            "cache_type": body.cache_type,
            "requested_context_size": requested_context,
            "projector_file_id": str(body.projector_file_id) if body.projector_file_id else None,
        },
    )
    task = task or create_task(
        session,
        title="Load " + model.filename,
        prompt="Load an existing local GGUF with llama.cpp",
        capability="runtime.load",
    )
    run = create_run(
        session,
        task,
        run_type="runtime",
        capability="runtime.load",
        executor_type="llama_load",
        execution_target="host",
        permissions=["manage_models", "filesystem_read"],
        retry_class="inspect",
        requested_resources={"gpus": body.gpus},
        parameters={
            "instance_id": instance.id,
            "model_path": model.host_path,
            "size_bytes": model.size_bytes,
            "mtime": model.mtime,
            "gpus": body.gpus,
            "context_size": body.context_size,
            "cache_type": body.cache_type,
            "requested_context_size": requested_context,
            "projector": projector,
        },
    )
    instance.endpoint = "llamacpp:" + instance.id
    instance.metadata_json = {**instance.metadata_json, "load_run_id": run.id, "operation_run_id": run.id}
    from app.runtime_coordination import add_runtime_intent

    add_runtime_intent(session, instance, run)
    return run


def request_stop(session, instance, *, task=None, ignore_run_id=None):
    if instance is None or instance.ownership != "managed" or instance.runtime_key != "llama.cpp":
        raise HTTPException(404, "Managed llama.cpp runtime not found")
    from app.runtime_coordination import foreign_runtime_work

    if foreign_runtime_work(session, instance):
        raise HTTPException(409, "Wait for the model's active work on another account before stopping it")
    active = session.scalars(
        select(Run).where(Run.executor_type.in_(["llama_load", "llama_stop"]), Run.status.not_in(TERMINAL))
    )
    if any(r.parameters.get("instance_id") == instance.id for r in active):
        raise HTTPException(409, "Cancel or wait for the current runtime operation first")
    consumers = session.scalars(select(Run).where(Run.status.not_in(TERMINAL)))
    if any(r.id != ignore_run_id and r.parameters.get("endpoint") == instance.endpoint for r in consumers):
        raise HTTPException(409, "Stop the model's active conversation or agent Run first")
    return enqueue_stop(session, instance, task=task)


@router.post("/{instance_id}/stop", status_code=202)
def stop(instance_id: UUID, session: DB):
    run = request_stop(session, session.get(RuntimeInstance, str(instance_id)))
    session.commit()
    return run_dict(run)


def managed_llama(session, instance_id):
    instance = session.get(RuntimeInstance, str(instance_id))
    if instance is None or instance.ownership != "managed" or instance.runtime_key != "llama.cpp":
        raise HTTPException(404, "Managed llama.cpp runtime not found")
    return instance


def active_instance_runs(session, instance_id, executors):
    for run in session.scalars(
        select(Run).where(Run.executor_type.in_(executors), Run.status.not_in(TERMINAL))
    ):
        if run.parameters.get("instance_id") == instance_id:
            return run
    return None


@router.post("/{instance_id}/health", status_code=202)
def health(instance_id: UUID, body: EmptyBody, session: DB):
    instance = managed_llama(session, instance_id)
    from app.runtime_coordination import foreign_runtime_work

    if foreign_runtime_work(
        session, instance, operations=("llama_load", "llama_stop", "llama_health")
    ) or active_instance_runs(session, instance.id, ("llama_load", "llama_stop", "llama_health")):
        raise HTTPException(409, "Cancel or wait for the current runtime operation first")
    task = create_task(
        session,
        title="Health " + instance.name,
        prompt="Inspect only this owned llama.cpp instance",
        capability="runtime.health",
    )
    run = create_run(
        session,
        task,
        run_type="runtime",
        capability="runtime.health",
        executor_type="llama_health",
        execution_target="host",
        permissions=["manage_models"],
        retry_class="safe",
        parameters={"instance_id": instance.id},
    )
    from app.data_access import ScopedSession

    if not isinstance(session, ScopedSession) or session.scope.administrator:
        instance.metadata_json = {**instance.metadata_json, "health_run_id": run.id}
    session.commit()
    return run_dict(run)


@router.post("/{instance_id}/restart", status_code=202)
def restart(instance_id: UUID, body: EmptyBody, session: DB):
    from app.dependencies import depend_on

    instance = managed_llama(session, instance_id)
    from app.runtime_coordination import foreign_runtime_work

    if instance.status == "unknown":
        raise HTTPException(409, "Inspect the runtime before restarting it")
    if (
        foreign_runtime_work(session, instance)
        or instance.status in {"queued", "loading", "stopping"}
        or active_instance_runs(session, instance.id, ("llama_load", "llama_stop", "llama_health"))
    ):
        raise HTTPException(409, "Cancel or wait for the current runtime operation first")
    meta = instance.metadata_json or {}
    file_id = meta.get("model_file_id")
    if not file_id:
        raise HTTPException(409, "This runtime has no saved model preset")
    stop_run = None
    if instance.status == "ready":
        stop_run = request_stop(session, instance)
    load_run = enqueue_load(
        LoadModel(
            model_file_id=file_id,
            gpus=list(meta.get("gpus") or []),
            context_size=int(meta.get("context_size") or 4096),
            cache_type=meta.get("cache_type") if meta.get("cache_type") in {"f16", "q8_0"} else "f16",
        ),
        session,
        allow_stopping=True,
    )
    if stop_run is not None:
        depend_on(session, load_run, stop_run)
        append_event(
            session,
            load_run.id,
            "runtime.restart_requested",
            {"previous_instance_id": instance.id, "stop_run_id": stop_run.id},
        )
    session.commit()
    return run_dict(load_run)


def enqueue_stop(session, instance, *, task=None):
    task = task or create_task(
        session,
        title="Stop " + instance.name,
        prompt="Unload only this owned runtime",
        capability="runtime.stop",
    )
    run = create_run(
        session,
        task,
        run_type="runtime",
        capability="runtime.stop",
        executor_type="llama_stop",
        execution_target="host",
        permissions=["manage_models"],
        retry_class="inspect",
        parameters={"instance_id": instance.id},
    )
    from app.runtime_coordination import register_runtime_stop

    register_runtime_stop(session, instance, run)
    instance.status = "stopping"
    instance.metadata_json = {**instance.metadata_json, "operation_run_id": run.id}
    return run


def reserve(session, run, indexes, *, hardware=None):
    selected = run.parameters["gpus"]
    if any(g not in indexes for g in selected):
        raise ValueError("Selected GPU is not present")
    own = {
        r.resource_key
        for r in session.scalars(
            select(ResourceLock).where(ResourceLock.run_id == run.id, ResourceLock.released_at.is_(None))
        )
    }
    requested = {f"gpu:{g}" for g in selected}
    if (active_locks(session) - own) & requested:
        return False
    from app.llama_admission import memory_available

    if not run.metadata_json.get("dispatch_attempted") and not memory_available(session, run, hardware):
        return False
    for key in requested - own:
        session.add(ResourceLock(resource_key=key, run_id=run.id))
    session.flush()
    run.allocated_resources = {"gpus": selected}
    return True


def _allocation_error(error: str) -> bool:
    text = (error or "").lower()
    return any(
        marker in text
        for marker in (
            "out of memory",
            "oom",
            "failed to allocate",
            "cuda malloc",
            "insufficient memory",
            "kv cache",
            "not enough memory",
        )
    )


def update_instance(session, instance, info):
    instance.status = info["status"]
    instance.updated_at = utcnow()
    meta = {**instance.metadata_json, "observation": info}
    n_ctx = info.get("n_ctx")
    if info["status"] == "ready" and isinstance(n_ctx, int) and n_ctx > 0:
        queued = int(meta.get("context_size") or n_ctx)
        meta["context_size"] = n_ctx
        if n_ctx < queued:
            meta["context_fit"] = "too_large"
            meta["failed_context_size"] = queued
        else:
            meta["context_fit"] = "ok"
        if isinstance(info.get("n_ctx_train"), int) and info["n_ctx_train"] > 0:
            meta["n_ctx_train"] = info["n_ctx_train"]
    elif info["status"] == "failed" and _allocation_error(str(info.get("error") or "")):
        meta["context_fit"] = "too_large"
    instance.metadata_json = meta
    from app.runtime_coordination import release_runtime_allocation

    release_runtime_allocation(session, instance, info)


class LlamaExecutor:
    def __init__(self, operation):
        self.operation = operation
        self.name = "llama_" + operation

    def fit_context(self, session, run, instance, runner, hardware):
        require(run.effective_permissions, "filesystem_read")
        try:
            report = runner.verify_model(
                {
                    "run_id": run.id,
                    "host_path": run.parameters["model_path"],
                    "size_bytes": run.parameters["size_bytes"],
                    "mtime": run.parameters["mtime"],
                    "check_context": True,
                    "permissions": run.effective_permissions,
                }
            )
        except (RunnerError, RunnerUnavailable):
            append_event(session, run.id, "runtime.context_estimated", {"source": "size_fallback"})
            return
        if not report.get("present") or not report.get("matches_observation"):
            instance.status = "failed"
            run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
            mark_failed(session, run, "ModelChanged", "Model changed since discovery; scan it again")
            return False
        profile = report.get("context_profile")
        if not profile:
            append_event(session, run.id, "runtime.context_estimated", {"source": "size_fallback"})
            return
        gpus = run.parameters["gpus"]
        totals = {int(item["index"]): item.get("memory_total_mib") for item in hardware.get("gpus", [])}
        memory = [totals.get(index) for index in gpus]
        fitted = fit_coding_context(
            gpus=gpus,
            size_bytes=run.parameters["size_bytes"]
            + (run.parameters.get("projector") or {}).get("size_bytes", 0),
            gpu_memory_mib=memory,
            ceiling=run.parameters.get("requested_context_size", run.parameters["context_size"]),
            failed_sizes=failed_context_sizes(session, instance.metadata_json["model_file_id"], gpus),
            proven_success=proven_context_size(session, instance.metadata_json["model_file_id"], gpus),
            context_profile=profile,
        )
        run.parameters = {**run.parameters, "context_size": fitted}
        instance.metadata_json = {
            **instance.metadata_json,
            "context_size": fitted,
            "context_profile": profile,
            "model_size_bytes": run.parameters["size_bytes"],
            "model_mtime": run.parameters["mtime"],
        }
        append_event(session, run.id, "runtime.context_estimated", {**profile, "context_size": fitted})

    def execute(self, session, run):
        require(run.effective_permissions, "manage_models")
        instance = session.get(RuntimeInstance, run.parameters["instance_id"])
        if instance is None or instance.ownership != "managed":
            raise ValueError("Owned runtime missing")
        session.refresh(run)
        if self.operation == "load":
            from app.llama_handoff import cancel_abandoned_restore

            cancel_abandoned_restore(session, run)
        elif run.parameters.get("evicted_for_run_id"):
            from app.llama_handoff import cancel_unneeded_eviction

            cancel_unneeded_eviction(session, run)
        if run.metadata_json.get("cancel_on_resume") and run.status != "cancel_requested":
            transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
        if run.status == "cancel_requested" and not run.metadata_json.get("dispatch_attempted"):
            instance.status = "stopped" if self.operation == "load" else "unknown"
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        if run.status != "cancel_requested":
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        session.commit()
        runner = RunnerClient()
        if self.operation == "load" and run.status != "cancel_requested":
            hardware = runner.hardware()
            indexes = [int(g["index"]) for g in hardware.get("gpus", [])]
            if run.parameters.get("cache_type") == "q8_0" and not run.metadata_json.get("dispatch_attempted"):
                if self.fit_context(session, run, instance, runner, hardware) is False:
                    return "done"
            session.refresh(run)
            if run.status == "cancel_requested":
                if not run.metadata_json.get("dispatch_attempted"):
                    instance.status = "stopped"
                    release_run_locks(session, run.id)
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                    return "done"
            elif not reserve(session, run, indexes, hardware=hardware):
                session.refresh(run)
                if run.status == "cancel_requested" and not run.metadata_json.get("dispatch_attempted"):
                    instance.status = "stopped"
                    release_run_locks(session, run.id)
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                    return "done"
                transition(session, run, RunStatus.INTERRUPTED, event_type="resource.waiting")
                transition(session, run, RunStatus.QUEUED, event_type="run.requeued")
                run.queued_at = utcnow()
                run.finished_at = None
                run.lease_expires_at = None
                evict_idle_models(session, run, indexes, desired=set(run.parameters["gpus"]))
                session.commit()
                return "requeued"
            if "resource_wait" in run.metadata_json:
                run.metadata_json = {
                    key: value for key, value in run.metadata_json.items() if key != "resource_wait"
                }
        session.refresh(run)
        if run.status != "cancel_requested":
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        instance.status = "loading" if self.operation == "load" else "stopping"
        session.commit()
        request = {
            key: run.parameters[key]
            for key in (
                "instance_id",
                "model_path",
                "size_bytes",
                "mtime",
                "gpus",
                "context_size",
                "cache_type",
                "projector",
            )
            if key in run.parameters
        }
        request.update(run_id=run.id, permissions=run.effective_permissions)
        deadline = time.monotonic() + max(
            0, 600 - (utcnow() - (run.started_at or run.created_at)).total_seconds()
        )
        try:
            if self.operation == "load" and run.status != "cancel_requested":
                info = runner.load_llama(request)
            else:
                info = runner.stop_llama(instance.id)
            run.pid = info.get("pid")
            run.runner_id = info.get("runner_id")
            run.metadata_json = {**run.metadata_json, "container_id": info.get("container_id")}
            while True:
                session.refresh(run)
                if self.operation == "load":
                    from app.llama_handoff import cancel_abandoned_restore

                    cancel_abandoned_restore(session, run)
                canceled = run.status == "cancel_requested"
                session.commit()
                from app.model_cancellation import foreign_demand, retain_ready

                retained = (
                    canceled
                    and self.operation == "load"
                    and time.monotonic() < deadline
                    and foreign_demand(session, run, instance)
                )
                if (canceled and not retained) or time.monotonic() >= deadline:
                    info = runner.stop_llama(instance.id)
                update_instance(session, instance, info)
                if retained and retain_ready(session, run, instance, info):
                    return "done"
                if not info.get("alive") and info["status"] in {"stopped", "failed"}:
                    run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
                    if canceled:
                        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                    elif self.operation == "stop":
                        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
                    else:
                        mark_failed(
                            session,
                            run,
                            "RuntimeFailed",
                            info.get("error") or "Runtime stopped before becoming ready",
                        )
                    return "done"
                if info["status"] == "ready" and self.operation == "load" and not canceled:
                    run.summary = f"{instance.name} ready on GPUs {run.parameters['gpus']}"
                    payload = {
                        "instance_id": instance.id,
                        "gpus": run.parameters["gpus"],
                        "context_size": instance.metadata_json.get("context_size"),
                        "cache_type": instance.metadata_json.get("cache_type", "f16"),
                    }
                    if isinstance(info.get("n_ctx"), int) and info["n_ctx"] > 0:
                        payload["n_ctx"] = info["n_ctx"]
                    if isinstance(info.get("n_ctx_train"), int) and info["n_ctx_train"] > 0:
                        payload["n_ctx_train"] = info["n_ctx_train"]
                    append_event(session, run.id, "runtime.ready", payload)
                    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
                    return "done"
                session.commit()
                time.sleep(0.5)
                info = runner.inspect_llama(instance.id)
        except RunnerError as exc:
            if exc.status_code == 404 and self.operation == "stop":
                update_instance(session, instance, {"status": "stopped", "alive": False})
                run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
                transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
                return "done"
            if exc.status_code < 500 and self.operation == "load":
                # Before accepting the immutable request, the Runner cannot launch.
                # A post-dispatch conflict must retain locks for inspection.
                if exc.status_code in {403, 422}:
                    update_instance(session, instance, {"status": "failed", "alive": False})
                    run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
                    mark_failed(session, run, "RuntimeRejected", str(exc))
                    return "done"
            raise


class LlamaHealthExecutor:
    name = "llama_health"

    def execute(self, session, run):
        require(run.effective_permissions, "manage_models")
        instance = session.get(RuntimeInstance, run.parameters["instance_id"])
        if instance is None or instance.ownership != "managed" or instance.runtime_key != "llama.cpp":
            mark_failed(session, run, "RuntimeMissing", "Owned llama.cpp runtime missing")
            return "done"
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(
            session, run, RunStatus.RUNNING, event_type="executor.started", payload={"mode": "inspect"}
        )
        session.commit()
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        try:
            info = RunnerClient().inspect_llama(instance.id)
        except RunnerError as exc:
            if exc.status_code == 404:
                info = {"status": "stopped", "alive": False, "error": "Managed container is gone"}
            elif exc.status_code < 500:
                mark_failed(session, run, "RunnerRejected", str(exc))
                return "done"
            else:
                raise
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        if instance.status in {"ready", "loading", "unknown", "stopping"} or info.get("alive"):
            update_instance(session, instance, info)
        from app.runtime_coordination import account_runtime_observation

        info = account_runtime_observation(session, info)
        health = {
            "status": info.get("status"),
            "alive": bool(info.get("alive")),
            "n_ctx": info.get("n_ctx"),
            "n_ctx_train": info.get("n_ctx_train"),
            "pid": info.get("pid"),
            "error": info.get("error") or "",
            "checked_at": utcnow().isoformat(),
        }
        instance.metadata_json = {**instance.metadata_json, "health": health, "health_run_id": run.id}
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump({"instance_id": instance.id, **health, "observation": info}, handle)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="runtime-health.json",
                run_id=run.id,
            )
        append_event(session, run.id, "runtime.health", health)
        run.summary = (
            f"{instance.name} is {health['status']}"
            + (f" · n_ctx {health['n_ctx']}" if isinstance(health["n_ctx"], int) else "")
            + ". External runtimes were not signalled."
        )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload=health)
        return "done"


def reconcile(session, runner):
    from app.runtime_coordination import foreign_runtime_work

    for instance in instances(session):
        if instance.status not in {"ready", "queued", "loading", "unknown", "stopping"}:
            continue
        if foreign_runtime_work(session, instance, operations=("llama_load", "llama_stop", "llama_health")):
            continue
        load = session.get(Run, instance.metadata_json.get("load_run_id"))
        operation = session.get(
            Run, instance.metadata_json.get("operation_run_id") or instance.metadata_json.get("load_run_id")
        )
        if operation and operation.status not in TERMINAL:
            continue
        if instance.status == "queued" and load and load.status in {"canceled", "failed"}:
            instance.status = "stopped" if load.status == "canceled" else "failed"
            session.commit()
            continue
        session.commit()
        try:
            info = runner.inspect_llama(instance.id)
        except RunnerError as exc:
            if exc.status_code != 404:
                continue
            info = {"status": "stopped", "alive": False}
        session.refresh(instance)
        if instance.status in {"ready", "loading", "unknown", "stopping"}:
            update_instance(session, instance, info)
            session.commit()


def model_endpoint(model, session, *, allow_pending=False):
    from app.providers import ProviderError

    try:
        file_id = str(UUID(model.removeprefix("llamacpp:")))
    except ValueError as exc:
        raise ProviderError("Invalid llama.cpp model selection") from exc
    for instance in instances(session):
        if instance.status == "ready" and instance.metadata_json.get("model_file_id") == file_id:
            return instance.endpoint
    if allow_pending:
        row = session.get(ModelFile, file_id)
        if loadable_model(row):
            return "llamacpp:pending:" + file_id
    raise ProviderError("Load the selected model with llama.cpp before sending a message")


def initial_preset(session, file_id):
    """Use explicit curated preferences, otherwise discovered local devices."""
    from app.model_definitions import preset_of
    from app.providers import ProviderError

    definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == file_id))
    if definition is not None and "gpus" in (definition.metadata_json or {}):
        return preset_of(definition)
    try:
        hardware = RunnerClient().hardware()
        if not isinstance(hardware.get("gpus"), list):
            raise ValueError("Missing device discovery")
        gpus = sorted({int(gpu["index"]) for gpu in hardware["gpus"]})
        if any(index < 0 for index in gpus) or len(gpus) > 16:
            raise ValueError("Invalid device discovery")
    except (RunnerError, RunnerUnavailable, ValueError, KeyError, TypeError) as exc:
        raise ProviderError(
            "Host Runner device discovery is unavailable; inspect System diagnostics"
        ) from exc
    return {"gpus": gpus, "context_size": 4096, "cache_type": "f16"}


def prepare_consumer(session, run):
    """Reuse a pending load or reload with the user's last saved GPU/context selection."""
    from app.coding_model_routing import MINIMUM_CONTEXT
    from app.dependencies import depend_on
    from app.providers import ProviderError
    from app.runtime_coordination import runtime_load_facts

    if run.status == "canceled":
        return
    model = run.parameters.get("model") or run.parameters.get("definition", {}).get("model", "")
    if not model.startswith("llamacpp:"):
        return
    file_id = model.removeprefix("llamacpp:")
    matching = [i for i in instances(session) if i.metadata_json.get("model_file_id") == file_id]
    try:
        matching.sort(
            key=lambda item: (runtime_load_facts(session, item)["created_at"], item.id), reverse=True
        )
    except ValueError as exc:
        raise ProviderError(str(exc)) from exc
    instance = next((i for i in matching if i.status in {"ready", "queued", "loading"}), None)
    coding = run.executor_type in {"local_proposal", "agent_data_generate"}
    target = 0
    if coding:
        row = session.get(ModelFile, file_id)
        if not loadable_model(row):
            raise ProviderError("Choose a present language-model GGUF; mmproj files are vision companions")
        source = instance or (matching[0] if matching else None)
        preset = source.metadata_json if source else initial_preset(session, file_id)
        target = coding_context_target(session, row, preset["gpus"])
    needs_upgrade = bool(
        instance is not None
        and target
        # An adequate live allocation need not be replaced to reach the next ideal preset.
        and instance.metadata_json.get("context_size", 4096) < MINIMUM_CONTEXT
        and (
            instance.metadata_json.get("cache_type", "f16") != "q8_0"
            or instance.metadata_json.get("context_size", 4096) < target
        )
    )
    if needs_upgrade:
        from app.runtime_coordination import foreign_runtime_work

        if foreign_runtime_work(session, instance):
            raise ProviderError("Wait for the model's active work before preparing its larger Coding context")
        consumers = session.scalars(select(Run).where(Run.status.not_in(TERMINAL), Run.id != run.id))
        if any(r.parameters.get("endpoint") == instance.endpoint for r in consumers):
            raise ProviderError("Wait for the model's active work before preparing its larger Coding context")
        previous_load = session.get(Run, instance.metadata_json["load_run_id"])
        stop_run = enqueue_stop(session, instance, task=session.get(Task, run.task_id))
        if previous_load is not None and previous_load.status not in TERMINAL:
            depend_on(session, stop_run, previous_load)
        append_event(
            session,
            run.id,
            "runtime.context_upgrade",
            {
                "previous_context": instance.metadata_json.get("context_size", 4096),
                "context_size": target,
                "cache_type": "q8_0",
                "context_ceiling": CODING_CONTEXT_CEILING,
            },
        )
        instance = None
    if instance is None:
        if any(i.status == "unknown" for i in matching):
            raise ProviderError("Inspect the model runtime before loading it again")
        preset = matching[0].metadata_json if matching else initial_preset(session, file_id)
        try:
            load_run = enqueue_load(
                LoadModel(
                    model_file_id=file_id,
                    gpus=preset["gpus"],
                    context_size=CODING_CONTEXT_CEILING if coding else preset["context_size"],
                    cache_type="q8_0" if coding else preset.get("cache_type", "f16"),
                ),
                session,
                task=session.get(Task, run.task_id),
                allow_stopping=True,
            )
        except HTTPException as exc:
            raise ProviderError(str(exc.detail)) from exc
        load_run.metadata_json = {**load_run.metadata_json, "created_for_consumer": run.id}
        for old in matching:
            if old.status == "stopping":
                operation = session.get(Run, old.metadata_json["operation_run_id"])
                if operation is None:
                    from app.runtime_coordination import wait_for_runtime

                    operation = wait_for_runtime(session, load_run, old, target="stopped")
                depend_on(session, load_run, operation)
        instance = session.get(RuntimeInstance, load_run.parameters["instance_id"])
    if instance.status != "ready":
        loading = session.get(Run, instance.metadata_json["load_run_id"])
        if loading is None:
            from app.runtime_coordination import wait_for_runtime

            loading = wait_for_runtime(session, run, instance)
        if loading.status in {"cancel_requested", "canceled", "failed", "interrupted"}:
            raise ProviderError("Wait for the selected model's canceled startup to finish before sending")
        depend_on(session, run, loading)
    run.parameters = {**run.parameters, "endpoint": instance.endpoint}


def evict_idle_models(session, run, indexes, *, desired=None):
    """Queue owned idle runtime stops to make room; never touch external services."""
    from app.dependencies import depend_on
    from app.llama_handoff import eviction_needed
    from app.runtime_coordination import foreign_runtime_work

    if not eviction_needed(session, run):
        return
    if desired is None:
        desired = set(indexes) if run.requested_gpu == "auto" else {int(run.requested_gpu)}
    consumers = list(session.scalars(select(Run).where(Run.status.not_in(TERMINAL))))
    for instance in instances(session):
        if instance.status != "ready" or not desired.intersection(instance.metadata_json.get("gpus", [])):
            continue
        if foreign_runtime_work(session, instance):
            continue
        references = [
            r
            for r in consumers
            if (
                r.parameters.get("endpoint") == instance.endpoint
                or r.parameters.get("instance_id") == instance.id
            )
        ]
        from app.llama_handoff import can_yield, publish_resumes

        if any(not can_yield(session, consumer, run, instance) for consumer in references):
            continue
        # Retained shared startup can outlive its original stopped Task. Its
        # resource support must not create new work in that stopped Task.
        task = None if run.task.metadata_json.get("stop_requested_at") else run.task
        stop_run = enqueue_stop(session, instance, task=task)
        stop_run.parameters = {**stop_run.parameters, "evicted_for_run_id": run.id}
        depend_on(session, run, stop_run)
        publish_resumes(session, references, run, instance, stop_run)
        append_event(
            session,
            run.id,
            "runtime.eviction_requested",
            {"instance_id": instance.id, "stop_run_id": stop_run.id},
        )
        if run.requested_gpu == "auto":
            break
