"""Minimal machine facts across private Runs; never an unscoped Run lookup."""

from copy import deepcopy
from datetime import datetime, timedelta

from sqlalchemy import and_, inspect, literal, or_, select, update

from app.data_access import ScopedSession
from app.models import Run
from app.state import TERMINAL


def runtime_ready_condition(now):
    """A private readiness waiter yields its worker between observations."""
    until = Run.metadata_json["runtime_wait_until"].as_string()
    return or_(Run.executor_type != "llama_wait", until.is_(None), until <= now.isoformat())


def wait_for_runtime(session, consumer, instance, *, target="ready"):
    """An owner-local prerequisite; never a foreign producer dependency."""
    from app.db import utcnow
    from app.models import Task
    from app.runs import create_run

    if target not in {"ready", "stopped"}:
        raise ValueError("Unknown managed model observation target")
    facts = runtime_load_facts(session, instance)
    operation = runtime_stop_facts(session, instance) if target == "stopped" else None
    deadline = utcnow() + timedelta(seconds=600)
    for key in ("execution_deadline_at", "agent_coding_deadline"):
        raw = consumer.parameters.get(key)
        if raw:
            deadline = min(deadline, datetime.fromisoformat(raw))
    return create_run(
        session,
        session.get(Task, consumer.task_id),
        run_type="runtime",
        capability="runtime.wait",
        executor_type="llama_wait",
        execution_target="container",
        retry_class="safe",
        parameters={
            "consumer_run_id": consumer.id,
            "instance_id": instance.id,
            "source": facts["source"],
            "startup_created_at": facts["created_at"].isoformat(),
            "target": target,
            **({"stop_created_at": operation["created_at"].isoformat()} if operation else {}),
            "execution_deadline_at": deadline.isoformat(),
        },
    )


class LlamaWaitExecutor:
    """Read shared lifecycle facts without dispatching or canceling host work."""

    name = "llama_wait"

    def execute(self, session, run):
        from app.db import utcnow
        from app.models import RuntimeInstance
        from app.runs import mark_failed, transition
        from app.state import RunStatus

        session.refresh(run)
        consumer = session.get(Run, run.parameters.get("consumer_run_id"))
        if (
            run.status == "cancel_requested"
            or run.metadata_json.get("cancel_on_resume")
            or consumer is None
            or consumer.status in TERMINAL | {"cancel_requested"}
        ):
            if run.status != "cancel_requested":
                transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        if datetime.fromisoformat(run.parameters["execution_deadline_at"]) <= utcnow():
            mark_failed(
                session, run, "RuntimeWaitExpired", "The model did not reach the requested state in time"
            )
            return "done"
        instance = session.get(RuntimeInstance, run.parameters["instance_id"])
        target = run.parameters.get("target", "ready")
        try:
            facts = runtime_load_facts(session, instance) if instance else None
            stop = runtime_stop_facts(session, instance) if instance and target == "stopped" else None
        except ValueError:
            facts = None
            stop = None
        valid_statuses = {"queued", "loading", "ready"} if target == "ready" else {"stopping", "stopped"}
        if (
            not facts
            or target not in {"ready", "stopped"}
            or facts["source"] != run.parameters["source"]
            or facts["created_at"].isoformat() != run.parameters["startup_created_at"]
            or target == "ready"
            and facts["status"] in TERMINAL - {"succeeded"} | {"cancel_requested"}
            and not facts["retained"]
            or instance.status not in valid_statuses
            or target == "stopped"
            and (
                not stop
                or stop["created_at"].isoformat() != run.parameters["stop_created_at"]
                or stop["status"] in TERMINAL - {"succeeded"} | {"cancel_requested"}
                and not stop["confirmed_stopped"]
            )
        ):
            mark_failed(
                session, run, "RuntimeUnavailable", "The selected model operation changed or did not succeed"
            )
            return "done"
        complete = (
            instance.status == "ready" and (facts["status"] == "succeeded" or facts["retained"])
            if target == "ready"
            else instance.status == "stopped"
            and (stop["status"] == "succeeded" or stop["confirmed_stopped"])
            and instance.metadata_json.get("observation", {}).get("alive") is False
        )
        if complete:
            transition(
                session,
                run,
                RunStatus.SUCCEEDED,
                event_type="runtime." + target,
                payload={"instance_id": instance.id},
            )
            return "done"
        transition(session, run, RunStatus.INTERRUPTED, event_type="runtime.waiting")
        transition(session, run, RunStatus.QUEUED, event_type="run.requeued")
        run.metadata_json = {
            **run.metadata_json,
            "runtime_wait_until": (utcnow() + timedelta(seconds=2)).isoformat(),
        }
        run.queued_at = utcnow()
        run.finished_at = None
        run.worker_id = None
        run.lease_expires_at = None
        return "requeued"


def add_runtime_intent(session, instance, run):
    """One new planned instance, derived from an already-owned queued load."""
    if isinstance(session, ScopedSession):
        if session.scope.read_only:
            raise ValueError("Runtime inspection cannot enqueue model operations")
        session.info.setdefault("_runtime_intents", {})[id(instance)] = {
            "run_id": run.id,
            "metadata": deepcopy(instance.metadata_json),
        }
    session.add(instance)


def consume_runtime_intent(session, instance):
    """Flush-only check; an existing row or altered plan never gets this grant."""
    from app.llama import loadable_model
    from app.model_sources import source_of
    from app.models import ModelFile, RuntimeInstance

    intent = session.info.get("_runtime_intents", {}).get(id(instance))
    if type(instance) is not RuntimeInstance or instance not in session.new or not intent:
        return False
    run = session.get(Run, intent["run_id"])
    model = session.get(ModelFile, instance.metadata_json.get("model_file_id"))
    if (
        run is None
        or run.owner_id != session.scope.user_id
        or run.status != "queued"
        or run.executor_type != "llama_load"
        or run.capability != "runtime.load"
        or run.execution_target != "host"
        or run.parameters.get("instance_id") != instance.id
        or not {"manage_models", "filesystem_read"} <= set(run.effective_permissions)
        or not loadable_model(model)
        or instance.name != model.filename
        or instance.ownership != "managed"
        or instance.runtime_key != "llama.cpp"
        or instance.status != "queued"
        or instance.endpoint != "llamacpp:" + instance.id
        or instance.metadata_json != intent["metadata"]
        or bool(run.parameters.get("app_owned")) != bool(model.relative_path)
        or run.parameters.get("model_sha256") != (model.sha256 if model.relative_path else None)
        or any(run.parameters.get(key) != value for key, value in source_of(model).items())
        or any(
            instance.metadata_json.get(key) != run.parameters.get(key)
            for key in (
                "gpus",
                "context_size",
                "cache_type",
                "requested_context_size",
                "runtime_profile",
                "ram_mib",
                "environment_id",
            )
        )
    ):
        return False
    session.info["_runtime_intents"].pop(id(instance))
    return True


def register_runtime_stop(session, instance, run):
    """Plan only the existing typed stop, preserving every other shared field."""
    if isinstance(session, ScopedSession):
        if session.scope.read_only:
            raise ValueError("Runtime inspection cannot enqueue model operations")
        session.info.setdefault("_runtime_stop_intents", {})[id(instance)] = {
            "run_id": run.id,
            "metadata": deepcopy(instance.metadata_json),
        }


def consume_runtime_stop(session, instance):
    from app.models import RuntimeInstance

    intent = session.info.get("_runtime_stop_intents", {}).get(id(instance))
    if (
        type(instance) is not RuntimeInstance
        or instance in session.new
        or instance in session.deleted
        or not intent
    ):
        return False
    run = session.get(Run, intent["run_id"])
    if (
        run is None
        or run.owner_id != session.scope.user_id
        or run.status != "queued"
        or run.executor_type != "llama_stop"
        or run.capability != "runtime.stop"
        or run.execution_target != "host"
        or "manage_models" not in run.effective_permissions
        or run.parameters.get("instance_id") != instance.id
        or instance.ownership != "managed"
        or instance.runtime_key != "llama.cpp"
        or instance.status != "stopping"
        or instance.metadata_json != {**intent["metadata"], "operation_run_id": run.id}
        or any(
            attribute.history.has_changes()
            for attribute in inspect(instance).attrs
            if attribute.key not in {"status", "metadata_json"}
        )
    ):
        return False
    session.info["_runtime_stop_intents"].pop(id(instance))
    return True


OBSERVATION_FIELDS = {
    "runner_id",
    "status",
    "alive",
    "container_id",
    "pid",
    "exit_code",
    "error",
    "gpus",
    "image_id",
    "n_ctx",
    "n_ctx_train",
    "n_params",
    "template_sha256",
    "checked_at",
    "compute_target",
    "ram_mib",
    "memory_enforcement",
    "zero_swap_guaranteed",
}


def account_runtime_observation(session, value):
    """Infrastructure observations can contain raw model-server error logs."""
    if not isinstance(session, ScopedSession) or session.scope.inspect_all:
        return dict(value)
    result = {key: value[key] for key in OBSERVATION_FIELDS if key in value}
    if result.get("error"):
        result["error"] = "The managed model reported an error. Inspect workstation diagnostics."
    return result


def runtime_load_facts(session, instance):
    """Project only immutable model source, status and startup time.

    A shared model can have a private initiating Run. Its complete Run, prompt,
    user, Task and events never cross this infrastructure boundary.
    """
    if isinstance(session, ScopedSession):
        session.scope
    if instance.ownership != "managed" or instance.runtime_key != "llama.cpp":
        raise ValueError("Model source requires a managed llama.cpp instance")
    fields = [
        Run.created_at,
        Run.status,
        Run.metadata_json["shared_model_retained"].as_boolean().label("retained"),
        Run.parameters["app_owned"].as_boolean().label("app_owned"),
    ]
    fields.extend(
        Run.parameters[key].label(key)
        for key in ("model_path", "size_bytes", "mtime", "projector", "gpus", "model_sha256")
    )
    result = (
        session.connection()
        .execute(
            select(*fields).where(
                Run.id == instance.metadata_json.get("load_run_id"),
                Run.executor_type == "llama_load",
                Run.parameters["instance_id"].as_string() == instance.id,
            )
        )
        .mappings()
        .first()
    )
    if result is None:
        raise ValueError("The managed model has no verified startup observation")
    source = {key: result[key] for key in ("model_path", "size_bytes", "mtime", "projector")}
    if result.get("app_owned") is True:
        source.update(app_owned=True, model_sha256=result["model_sha256"])
    if (
        not isinstance(source["model_path"], str)
        or not source["model_path"]
        or type(source["size_bytes"]) is not int
        or source["size_bytes"] < 0
        or type(source["mtime"]) not in {int, float}
        or source["projector"] is not None
        and not isinstance(source["projector"], dict)
    ):
        raise ValueError("The managed model source observation is incomplete")
    from app.models import RunEvent

    retained = (
        result["retained"] is True
        and result["status"] == "canceled"
        and session.connection().scalar(
            select(literal(1))
            .select_from(RunEvent.__table__)
            .where(
                RunEvent.run_id == instance.metadata_json.get("load_run_id"),
                RunEvent.event_type == "runtime.ready",
                RunEvent.payload["instance_id"].as_string() == instance.id,
            )
            .limit(1)
        )
        is not None
    )
    return {
        "created_at": result["created_at"],
        "status": result["status"],
        "source": source,
        "gpus": result["gpus"],
        "retained": retained,
    }


def runtime_coding_facts(session, instance):
    """Verified public allocation proof for Auto selection, including stopped models."""
    from app.models import RunEvent

    facts = runtime_load_facts(session, instance)
    gpus = facts["gpus"]
    if not isinstance(gpus, list) or any(type(index) is not int or index < 0 for index in gpus):
        raise ValueError("The model has no verified device observation")
    ready = (
        session.connection()
        .execute(
            select(
                *(RunEvent.payload[key].label(key) for key in ("instance_id", "gpus", "cache_type", "n_ctx"))
            )
            .where(
                RunEvent.run_id == instance.metadata_json.get("load_run_id"),
                RunEvent.event_type == "runtime.ready",
                RunEvent.payload["instance_id"].as_string() == instance.id,
            )
            .order_by(RunEvent.sequence.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    return {**facts, "ready_observation": dict(ready) if ready else {}}


def runtime_stop_facts(session, instance):
    """Only the lifecycle of this exact managed stop; no private operation ID."""
    if isinstance(session, ScopedSession):
        session.scope
    if instance.ownership != "managed" or instance.runtime_key != "llama.cpp":
        raise ValueError("Stop observation requires a managed llama.cpp instance")
    facts = (
        session.connection()
        .execute(
            select(
                Run.created_at,
                Run.status,
                Run.metadata_json["process_confirmed_gone"].as_boolean().label("confirmed_stopped"),
            ).where(
                Run.id == instance.metadata_json.get("operation_run_id"),
                or_(
                    Run.executor_type == "llama_stop",
                    and_(
                        Run.executor_type == "llama_load",
                        Run.metadata_json["load_shutdown_requested"].as_boolean().is_(True),
                    ),
                ),
                Run.parameters["instance_id"].as_string() == instance.id,
            )
        )
        .mappings()
        .first()
    )
    if facts is None:
        raise ValueError("The selected model has no verified stop operation")
    return dict(facts)


def foreign_runtime_work(session, instance, *, operations=None):
    """Only a busy boolean for this managed model, without IDs or user content.

    Ordinary ORM sessions already coordinate all Runs. Owner-scoped sessions
    need this fixed infrastructure projection before changing a shared runtime.
    """
    if not isinstance(session, ScopedSession):
        return False
    scope = session.scope
    if instance.ownership != "managed" or instance.runtime_key != "llama.cpp":
        raise ValueError("Runtime coordination requires a managed llama.cpp instance")
    if operations is not None and not set(operations) <= {"llama_load", "llama_stop", "llama_health"}:
        raise ValueError("Unknown managed model operation")
    query = (
        select(literal(1))
        .select_from(Run.__table__)
        .where(
            Run.status.not_in(TERMINAL),
            or_(Run.owner_id.is_(None), Run.owner_id != scope.user_id),
            or_(
                Run.parameters["instance_id"].as_string() == instance.id,
                Run.parameters["endpoint"].as_string() == instance.endpoint,
            ),
        )
    )
    if operations is not None:
        query = query.where(Run.executor_type.in_(operations))
    return session.connection().scalar(query.limit(1)) is not None


def shared_load_in_use(session, load):
    """Keep a startup needed by another account when its original Task stops."""
    from app.models import RuntimeInstance

    if load.executor_type != "llama_load":
        return False
    instance = session.get(RuntimeInstance, load.parameters.get("instance_id"))
    return bool(instance and foreign_runtime_work(session, instance))


def release_runtime_allocation(session, instance, observation):
    """Release only this confirmed-gone model's physical reservations.

    This fixed coordinator cannot mutate the producer, its Task or events. GPU
    and RAM keys come from the validated loader; other reservations survive.
    """
    from app.db import utcnow
    from app.models import ResourceLock
    from app.resources import release_run_locks

    if observation.get("alive") is not False or observation.get("status") not in {"stopped", "failed"}:
        return
    loader_id = instance.metadata_json.get("load_run_id")
    if not isinstance(session, ScopedSession) or session.get(Run, loader_id) is not None:
        release_run_locks(session, loader_id)
        return
    scope = session.scope
    if scope.read_only or not (scope.execution or scope.administrator):
        raise ValueError("Physical allocation release requires managed runtime execution")
    runtime_load_facts(session, instance)
    loader = (
        session.connection()
        .execute(
            select(Run.parameters["gpus"].label("gpus")).where(
                Run.id == loader_id,
                Run.executor_type == "llama_load",
                Run.parameters["instance_id"].as_string() == instance.id,
            )
        )
        .mappings()
        .one()
    )
    gpus = loader["gpus"]
    if not isinstance(gpus, list) or any(type(index) is not int or index < 0 for index in gpus):
        raise ValueError("The model allocation has no verified device observation")
    session.connection().execute(
        update(ResourceLock)
        .where(
            ResourceLock.run_id == loader_id,
            ResourceLock.released_at.is_(None),
            ResourceLock.resource_key.in_([*(f"gpu:{index}" for index in gpus), "ram:" + loader_id]),
        )
        .values(released_at=utcnow())
    )
