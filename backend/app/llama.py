"""Model selection and durable ownership of llama.cpp runtime lifecycle."""

import re
import time
from pathlib import PurePosixPath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.events import append_event
from app.models import ModelFile, ResourceLock, Run, RuntimeInstance, Task
from app.permissions import require
from app.resources import active_locks, release_run_locks
from app.runner_client import RunnerClient, RunnerError
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.serialize import runtime_dict
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/llama")
DB = Annotated[Session, Depends(session_scope)]


class LoadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_file_id: UUID
    gpus: list[Annotated[int, Field(ge=0)]] = Field(max_length=16)
    context_size: int = Field(default=4096, ge=512, le=32768, multiple_of=256)


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


@router.get("")
def catalog(session: DB):
    return {
        "models": [
            {
                "id": row.id,
                "name": f"{PurePosixPath(row.host_path).parent.name} · {row.filename}",
                "size_bytes": row.size_bytes,
                "model_key": "llamacpp:" + row.id,
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


def enqueue_load(body, session, *, task=None, allow_stopping=False):
    model = session.get(ModelFile, str(body.model_file_id))
    if not loadable_model(model):
        raise HTTPException(422, "Choose a present language-model GGUF; mmproj files are vision companions")
    if len(set(body.gpus)) != len(body.gpus):
        raise HTTPException(422, "Choose distinct GPUs")
    for instance in instances(session):
        if instance.metadata_json.get("model_file_id") == model.id and instance.status not in {
            "stopped",
            "failed",
            *(["stopping"] if allow_stopping else []),
        }:
            raise HTTPException(409, "This model already has a runtime; inspect it before loading again")
    instance = RuntimeInstance(
        runtime_key="llama.cpp",
        name=model.filename,
        ownership="managed",
        status="queued",
        metadata_json={"model_file_id": model.id, "gpus": body.gpus, "context_size": body.context_size},
    )
    session.add(instance)
    session.flush()
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
        },
    )
    instance.endpoint = "llamacpp:" + instance.id
    instance.metadata_json = {**instance.metadata_json, "load_run_id": run.id, "operation_run_id": run.id}
    return run


@router.post("/{instance_id}/stop", status_code=202)
def stop(instance_id: UUID, session: DB):
    instance = session.get(RuntimeInstance, str(instance_id))
    if instance is None or instance.ownership != "managed" or instance.runtime_key != "llama.cpp":
        raise HTTPException(404, "Managed llama.cpp runtime not found")
    active = session.scalars(
        select(Run).where(Run.executor_type.in_(["llama_load", "llama_stop"]), Run.status.not_in(TERMINAL))
    )
    if any(r.parameters.get("instance_id") == instance.id for r in active):
        raise HTTPException(409, "Cancel or wait for the current runtime operation first")
    consumers = session.scalars(select(Run).where(Run.status.not_in(TERMINAL)))
    if any(r.parameters.get("endpoint") == instance.endpoint for r in consumers):
        raise HTTPException(409, "Stop the model's active conversation or agent Run first")
    run = enqueue_stop(session, instance)
    session.commit()
    return run_dict(run)


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
    instance.status = "stopping"
    instance.metadata_json = {**instance.metadata_json, "operation_run_id": run.id}
    return run


def reserve(session, run, indexes):
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
    for key in requested - own:
        session.add(ResourceLock(resource_key=key, run_id=run.id))
    session.flush()
    run.allocated_resources = {"gpus": selected}
    return True


def update_instance(session, instance, info):
    instance.status = info["status"]
    instance.updated_at = utcnow()
    instance.metadata_json = {**instance.metadata_json, "observation": info}
    if not info.get("alive") and info["status"] in {"stopped", "failed"}:
        release_run_locks(session, instance.metadata_json["load_run_id"])


class LlamaExecutor:
    def __init__(self, operation):
        self.operation = operation
        self.name = "llama_" + operation

    def execute(self, session, run):
        require(run.effective_permissions, "manage_models")
        instance = session.get(RuntimeInstance, run.parameters["instance_id"])
        if instance is None or instance.ownership != "managed":
            raise ValueError("Owned runtime missing")
        session.refresh(run)
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
            indexes = [int(g["index"]) for g in runner.hardware().get("gpus", [])]
            session.refresh(run)
            if run.status == "cancel_requested":
                if not run.metadata_json.get("dispatch_attempted"):
                    instance.status = "stopped"
                    release_run_locks(session, run.id)
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                    return "done"
            elif not reserve(session, run, indexes):
                transition(session, run, RunStatus.INTERRUPTED, event_type="resource.waiting")
                transition(session, run, RunStatus.QUEUED, event_type="run.requeued")
                run.queued_at = utcnow()
                run.finished_at = None
                run.lease_expires_at = None
                evict_idle_models(session, run, indexes, desired=set(run.parameters["gpus"]))
                session.commit()
                return "requeued"
        session.refresh(run)
        if run.status != "cancel_requested":
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        instance.status = "loading" if self.operation == "load" else "stopping"
        session.commit()
        payload = {**run.parameters, "run_id": run.id, "permissions": run.effective_permissions}
        deadline = time.monotonic() + max(
            0, 600 - (utcnow() - (run.started_at or run.created_at)).total_seconds()
        )
        try:
            if self.operation == "load" and run.status != "cancel_requested":
                info = runner.load_llama(payload)
            else:
                info = runner.stop_llama(instance.id)
            run.pid = info.get("pid")
            run.runner_id = info.get("runner_id")
            run.metadata_json = {**run.metadata_json, "container_id": info.get("container_id")}
            while True:
                session.refresh(run)
                canceled = run.status == "cancel_requested"
                session.commit()
                if canceled or time.monotonic() >= deadline:
                    info = runner.stop_llama(instance.id)
                update_instance(session, instance, info)
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
                    append_event(
                        session,
                        run.id,
                        "runtime.ready",
                        {"instance_id": instance.id, "gpus": run.parameters["gpus"]},
                    )
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


def reconcile(session, runner):
    for instance in instances(session):
        if instance.status not in {"ready", "queued", "loading", "unknown", "stopping"}:
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
        if loadable_model(row) and any(
            i.metadata_json.get("model_file_id") == file_id for i in instances(session)
        ):
            return "llamacpp:pending:" + file_id
    raise ProviderError("Load the selected model with llama.cpp before sending a message")


def prepare_consumer(session, run):
    """Reuse a pending load or reload with the user's last saved GPU/context selection."""
    from app.dependencies import depend_on
    from app.providers import ProviderError

    model = run.parameters.get("model") or run.parameters.get("definition", {}).get("model", "")
    if not model.startswith("llamacpp:"):
        return
    file_id = model.removeprefix("llamacpp:")
    matching = [i for i in instances(session) if i.metadata_json.get("model_file_id") == file_id]
    matching.sort(
        key=lambda i: (session.get(Run, i.metadata_json["load_run_id"]).created_at, i.id), reverse=True
    )
    instance = next((i for i in matching if i.status in {"ready", "queued", "loading"}), None)
    if instance is None:
        if not matching:
            raise ProviderError("Choose GPUs and load this model once in conversation settings")
        if any(i.status == "unknown" for i in matching):
            raise ProviderError("Inspect the model runtime before loading it again")
        preset = matching[0].metadata_json
        try:
            load_run = enqueue_load(
                LoadModel(model_file_id=file_id, gpus=preset["gpus"], context_size=preset["context_size"]),
                session,
                task=session.get(Task, run.task_id),
                allow_stopping=True,
            )
        except HTTPException as exc:
            raise ProviderError(str(exc.detail)) from exc
        for old in matching:
            if old.status == "stopping":
                operation = session.get(Run, old.metadata_json["operation_run_id"])
                depend_on(session, load_run, operation)
        instance = session.get(RuntimeInstance, load_run.parameters["instance_id"])
    if instance.status != "ready":
        depend_on(session, run, session.get(Run, instance.metadata_json["load_run_id"]))
    run.parameters = {**run.parameters, "endpoint": instance.endpoint}


def evict_idle_models(session, run, indexes, *, desired=None):
    """Queue owned idle runtime stops to make room; never touch external services."""
    from app.dependencies import depend_on

    if desired is None:
        desired = set(indexes) if run.requested_gpu == "auto" else {int(run.requested_gpu)}
    consumers = list(session.scalars(select(Run).where(Run.status.not_in(TERMINAL))))
    for instance in instances(session):
        if instance.status != "ready" or not desired.intersection(instance.metadata_json.get("gpus", [])):
            continue
        if any(
            r.parameters.get("endpoint") == instance.endpoint
            or r.parameters.get("instance_id") == instance.id
            for r in consumers
        ):
            continue
        stop_run = enqueue_stop(session, instance, task=session.get(Task, run.task_id))
        depend_on(session, run, stop_run)
        append_event(
            session,
            run.id,
            "runtime.eviction_requested",
            {"instance_id": instance.id, "stop_run_id": stop_run.id},
        )
        if run.requested_gpu == "auto":
            break
