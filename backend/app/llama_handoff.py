"""Dependency-bound, lazy restoration of an explicitly selected owned model."""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select

from app.db import utcnow
from app.dependencies import active_dependents, depend_on
from app.events import append_event
from app.models import ModelFile, Run, RunDependency, RuntimeInstance, Task
from app.runs import create_run, request_cancel, transition
from app.state import TERMINAL, RunStatus

NAME = "llama_resume_consumer"
KEY = "runtime_handoff"


def eviction_needed(session, requester):
    session.refresh(requester, ["status"])
    session.refresh(requester.task, ["metadata_json"])
    return requester.status == "queued" and (
        not requester.task.metadata_json.get("stop_requested_at")
        or requester.executor_type == "llama_load"
        and active_dependents(session, requester, other_tasks=True)
    )


def cancel_unneeded_eviction(session, stop):
    from app.task_control import lock_task

    requester = session.get(Run, stop.parameters.get("evicted_for_run_id"))
    if requester is None:
        raise ValueError("Owned eviction has no requesting Run")
    lock_task(session, requester.task)
    expire_consumer(session, requester)
    if requester.executor_type == "llama_load":
        cancel_abandoned_restore(session, requester)
    if not eviction_needed(session, requester):
        if requester.status == "queued":
            request_cancel(session, requester)
        if not active_dependents(session, stop, exclude_run_id=requester.id):
            append_event(
                session,
                stop.id,
                "runtime.eviction_abandoned",
                {
                    "requesting_run_id": requester.id,
                    "reason": "Requesting work stopped or no longer needs this resource.",
                },
            )
            request_cancel(session, stop)


def expire_consumer(session, consumer):
    from app.heartbeat import cancel_expired_run

    cancel_expired_run(session, consumer.id)
    if (
        consumer.status == "queued"
        and consumer.parameters.get("deadline_at")
        and datetime.fromisoformat(consumer.parameters["deadline_at"]) <= utcnow()
    ):
        request_cancel(session, consumer)


def cancel_abandoned_restore(session, load):
    """Do not start/keep an owned reload after its last real consumer stops.

    A later independent consumer can share the ordinary load. Its reference
    keeps the load alive; the original Task's budget cannot cancel that work.
    """
    marker = load.metadata_json.get("runtime_handoff_resume_id")
    if marker is None or load.status == "cancel_requested":
        return
    from app.task_control import lock_task

    # Serialize with message/Task creation before deciding that no independent
    # consumer remains. Never hold this lock during a native request.
    lock_task(session, load.task)
    resume = session.get(Run, marker)
    if resume is not None:
        session.refresh(resume)
    if (
        resume is None
        or resume.executor_type != NAME
        or resume.status != "succeeded"
        or resume.task_id != load.task_id
        or resume.metadata_json.get("load_run_id") != load.id
        or resume.metadata_json.get("instance_id") != load.parameters.get("instance_id")
    ):
        raise ValueError("Restored model startup has no verified preparation Run")
    consumers = list(
        session.scalars(
            select(Run)
            .join(RunDependency, RunDependency.run_id == Run.id)
            .where(RunDependency.prerequisite_id == load.id, Run.status.not_in(TERMINAL))
            .execution_options(populate_existing=True)
            .limit(1025)
        )
    )
    if len(consumers) > 1024:
        return  # Never stop shared work based on a truncated reference set.
    for consumer in consumers:
        expire_consumer(session, consumer)
    if not any(consumer.status not in TERMINAL | {"cancel_requested"} for consumer in consumers):
        append_event(session, load.id, "runtime.restore_abandoned", {})
        request_cancel(session, load)


def consumer_identity(consumer):
    return hashlib.sha256(
        json.dumps(
            {
                "parameters": consumer.parameters,
                "permissions": consumer.effective_permissions,
                "executor": consumer.executor_type,
                "execution_target": consumer.execution_target,
                "capability": consumer.capability,
                "requested_resources": consumer.requested_resources,
                "requested_gpu": consumer.requested_gpu,
                "task_id": consumer.task_id,
                "project_id": consumer.project_id,
                "agent_id": consumer.agent_id,
                "conversation_id": consumer.conversation_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def original_observation(session, instance):
    load = session.get(Run, instance.metadata_json.get("load_run_id"))
    if (
        load is None
        or load.executor_type != "llama_load"
        or load.status != "succeeded"
        or load.parameters.get("instance_id") != instance.id
    ):
        raise ValueError("The original model startup is not verified")
    observation = {
        key: load.parameters.get(key) for key in ("model_path", "size_bytes", "mtime", "projector")
    }
    if (
        not isinstance(observation["model_path"], str)
        or not observation["model_path"]
        or not isinstance(observation["size_bytes"], int)
        or observation["size_bytes"] < 0
        or not isinstance(observation["mtime"], (int, float))
    ):
        raise ValueError("The original model source observation is incomplete")
    return observation


def waits_for(session, consumer_id, prerequisite_id):
    frontier, seen = {consumer_id}, set()
    while frontier:
        if len(seen | frontier) > 1024:
            return False
        if prerequisite_id in frontier:
            return True
        seen |= frontier
        frontier = (
            set(
                session.scalars(
                    select(RunDependency.prerequisite_id).where(RunDependency.run_id.in_(frontier))
                )
            )
            - seen
        )
    return False


def selected_model(run):
    return run.parameters.get("model") or (run.parameters.get("definition") or {}).get("model")


def preset(instance):
    from app.llama import LoadModel

    meta = instance.metadata_json
    return LoadModel(
        model_file_id=meta["model_file_id"],
        gpus=meta["gpus"],
        context_size=meta["context_size"],
        cache_type=meta.get("cache_type", "f16"),
        projector_file_id=meta.get("projector_file_id"),
    ).model_dump(mode="json")


def can_yield(session, consumer, requester, instance):
    if (
        consumer.id == requester.id
        or consumer.status != "queued"
        or consumer.metadata_json.get("dispatch_attempted")
        or selected_model(consumer) != "llamacpp:" + instance.metadata_json.get("model_file_id", "")
        or consumer.parameters.get("endpoint") != instance.endpoint
        or not waits_for(session, consumer.id, requester.id)
    ):
        return False
    try:
        preset(instance)
        original_observation(session, instance)
    except (KeyError, TypeError, ValueError):
        return False
    return True


def publish_resumes(session, consumers, requester, instance, stop):
    for consumer in consumers:
        snapshot = preset(instance)
        root = session.get(Task, consumer.task_id)
        parameters = {
            "consumer_run_id": consumer.id,
            "requester_run_id": requester.id,
            "old_instance_id": instance.id,
            "old_endpoint": instance.endpoint,
            "preset": snapshot,
            "stop_run_id": stop.id,
            "consumer_model": selected_model(consumer),
            "consumer_identity": consumer_identity(consumer),
            "model_observation": original_observation(session, instance),
        }
        resume = create_run(
            session,
            root,
            run_type="runtime",
            capability="runtime.resume_consumer",
            executor_type=NAME,
            execution_target="container",
            retry_class="safe",
            operation_key=f"model-handoff:{consumer.id}:{instance.id}:{requester.id}",
            parameters=parameters,
            permissions=["manage_models", "filesystem_read"],
            parent_run_id=consumer.id,
            triggered_by=consumer.triggered_by,
        )
        resume.summary = "Waiting for earlier work before preparing the selected model."
        original = list(
            session.scalars(select(RunDependency.prerequisite_id).where(RunDependency.run_id == consumer.id))
        )
        for rid in original:
            depend_on(session, resume, session.get(Run, rid))
        depend_on(session, resume, stop)
        depend_on(session, consumer, resume)
        consumer.metadata_json = {**consumer.metadata_json, KEY: {"resume_run_id": resume.id, **parameters}}
        append_event(
            session,
            consumer.id,
            "runtime.consumer_yielded",
            {
                "resume_run_id": resume.id,
                "instance_id": instance.id,
                "prerequisite_id": requester.id,
            },
        )


class LlamaResumeConsumerExecutor:
    name = NAME

    def execute(self, session, run):
        from app.llama import LoadModel, enqueue_load, instances, loadable_model
        from app.permissions import require
        from app.task_control import lock_task

        require(run.effective_permissions, "manage_models")
        require(run.effective_permissions, "filesystem_read")
        lock_task(session, run.task)
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        p = run.parameters
        consumer = session.get(Run, p.get("consumer_run_id"))
        if consumer is not None:
            session.refresh(consumer)
            expire_consumer(session, consumer)
            if run.task.metadata_json.get("stop_requested_at") and consumer.status == "queued":
                request_cancel(session, consumer)
        if consumer is not None and consumer.status in TERMINAL | {"cancel_requested"}:
            request_cancel(session, run)
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        old = session.get(RuntimeInstance, p.get("old_instance_id"))
        if (
            consumer is None
            or consumer.status != "queued"
            or consumer.task_id != run.task_id
            or run.parent_run_id != consumer.id
            or consumer.metadata_json.get(KEY) != {"resume_run_id": run.id, **p}
            or selected_model(consumer) != p.get("consumer_model")
            or consumer.parameters.get("endpoint") != p.get("old_endpoint")
            or consumer_identity(consumer) != p.get("consumer_identity")
            or old is None
            or old.ownership != "managed"
            or old.runtime_key != "llama.cpp"
            or old.status != "stopped"
            or preset(old) != p.get("preset")
            or old.endpoint != p.get("old_endpoint")
            or original_observation(session, old) != p.get("model_observation")
            or not waits_for(session, consumer.id, run.id)
        ):
            raise ValueError("Deferred model preparation no longer matches its queued consumer")
        stop = session.get(Run, p.get("stop_run_id"))
        requester = session.get(Run, p.get("requester_run_id"))
        if (
            stop is None
            or stop.executor_type != "llama_stop"
            or stop.status != "succeeded"
            or stop.parameters.get("instance_id") != old.id
            or requester is None
            or requester.status != "succeeded"
            or not waits_for(session, run.id, requester.id)
            or not waits_for(session, run.id, stop.id)
        ):
            raise ValueError("Deferred model preparation lacks its completed prerequisite and owned stop")
        model = session.get(ModelFile, p["preset"]["model_file_id"])
        if not loadable_model(model):
            raise ValueError("The selected model is no longer available")
        observation = p["model_observation"]
        if {"model_path": model.host_path, "size_bytes": model.size_bytes, "mtime": model.mtime} != {
            key: observation[key] for key in ("model_path", "size_bytes", "mtime")
        }:
            raise ValueError("The selected model changed while its consumer was waiting")
        matching = [
            item
            for item in instances(session)
            if item.metadata_json.get("model_file_id") == model.id
            and item.status not in {"stopped", "failed"}
        ]
        if any(
            item.status not in {"ready", "queued", "loading"} or preset(item) != p["preset"]
            for item in matching
        ):
            raise ValueError("Inspect the changed or uncertain model runtime before resuming")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        if len(matching) > 1:
            raise ValueError("Inspect multiple active model runtimes before resuming")
        if matching:
            instance = matching[0]
            load = session.get(Run, instance.metadata_json["load_run_id"])
        else:
            # This exact previously fitted preset is enqueued without hardware
            # I/O under the Task lock. The normal native load rechecks admission,
            # file observation and context fit before any process is dispatched.
            load = enqueue_load(
                LoadModel.model_validate(p["preset"]), session, task=run.task, _fitted_context=True
            )
            load.metadata_json = {**load.metadata_json, "runtime_handoff_resume_id": run.id}
            instance = session.get(RuntimeInstance, load.parameters["instance_id"])
        if load is not None and {key: load.parameters.get(key) for key in observation} != observation:
            raise ValueError("The restored model no longer matches its original source observation")
        if load is None or load.status in {"canceled", "failed", "interrupted", "cancel_requested"}:
            raise ValueError("Inspect the selected model's failed or canceled startup")
        consumer.parameters = {**consumer.parameters, "endpoint": instance.endpoint}
        if instance.status != "ready":
            depend_on(session, consumer, load)
        run.metadata_json = {**run.metadata_json, "instance_id": instance.id, "load_run_id": load.id}
        run.summary = (
            "Selected model is ready; waiting work prepared."
            if instance.status == "ready"
            else "Model reload queued; waiting work is linked to its startup."
        )
        append_event(session, consumer.id, "runtime.consumer_prepared", run.metadata_json)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"
