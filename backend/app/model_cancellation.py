"""Owned model cancellation observes infrastructure without reviving user work."""

from datetime import timedelta

from sqlalchemy import literal, or_, select, update

from app.data_access import DataAccessError, ScopedSession
from app.db import utcnow
from app.events import append_event
from app.models import Run, RuntimeInstance, User
from app.resources import release_run_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import touch_lease, transition
from app.state import TERMINAL, RunStatus


def validate_load(run, instance):
    if (
        instance is None
        or instance.ownership != "managed"
        or instance.runtime_key != "llama.cpp"
        or run.owner_id is None
        or run.task is None
        or run.task.owner_id != run.owner_id
        or run.executor_type != "llama_load"
        or run.capability != "runtime.load"
        or run.execution_target != "host"
        or not {"manage_models", "filesystem_read"} <= set(run.effective_permissions)
        or run.parameters.get("instance_id") != instance.id
        or instance.metadata_json.get("load_run_id") != run.id
        or any(instance.metadata_json.get(key) != run.parameters.get(key) for key in ("gpus", "cache_type"))
    ):
        raise ValueError("The canceled model has no verified owned startup")


def foreign_demand(session, run, instance):
    """Only a live demand bit crosses account boundaries; never private rows."""
    if isinstance(session, ScopedSession):
        session.scope
    work, users = Run.__table__, User.__table__
    return (
        session.connection().scalar(
            select(literal(1))
            .select_from(work.join(users, work.c.owner_id == users.c.id))
            .where(
                work.c.owner_id != run.owner_id,
                work.c.status.not_in(TERMINAL | {"cancel_requested"}),
                work.c.executor_type != "llama_stop",
                or_(
                    work.c.executor_type != "llama_wait",
                    work.c.parameters["target"].as_string().is_(None),
                    work.c.parameters["target"].as_string() != "stopped",
                ),
                users.c.enabled.is_(True),
                users.c.bootstrap_pending.is_(False),
                (work.c.parameters["instance_id"].as_string() == instance.id)
                | (work.c.parameters["endpoint"].as_string() == instance.endpoint),
            )
            .limit(1)
        )
        is not None
    )


def before_deadline(run):
    return utcnow() < (run.started_at or run.created_at) + timedelta(seconds=600)


def quarantine_changed_load(session, run, instance):
    try:
        validate_load(run, instance)
    except ValueError:
        run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
        transition(session, run, RunStatus.INTERRUPTED, event_type="recovery.inspection_required")
        session.commit()
        return True
    return False


def retire_unstarted_load(session, run):
    """Cancel a queued owned plan without granting general shared-row writes."""
    if (
        run.owner_id is None
        or run.executor_type != "llama_load"
        or run.metadata_json.get("dispatch_attempted")
    ):
        return
    if isinstance(session, ScopedSession) and (
        session.scope.read_only or session.scope.user_id != run.owner_id
    ):
        raise DataAccessError("Only the owner can retire an unstarted model plan")
    if run.status != "canceled":
        raise ValueError("Retiring a model requires its queued cancellation")
    instance = session.get(RuntimeInstance, run.parameters.get("instance_id"))
    try:
        validate_load(run, instance)
    except ValueError:
        run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
        return
    table = RuntimeInstance.__table__
    result = session.connection().execute(
        update(table)
        .where(
            table.c.id == instance.id,
            table.c.status == "queued",
            table.c.metadata["load_run_id"].as_string() == run.id,
        )
        .values(status="stopped", updated_at=utcnow())
    )
    if result.rowcount == 1:
        session.expire(instance)
        run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
        release_run_locks(session, run.id)
    else:
        run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}


def record_ready(session, run, instance, info):
    payload = {
        "instance_id": instance.id,
        "gpus": run.parameters["gpus"],
        "context_size": instance.metadata_json.get("context_size"),
        "cache_type": instance.metadata_json.get("cache_type", "f16"),
    }
    for key in ("n_ctx", "n_ctx_train"):
        if type(info.get(key)) is int and info[key] > 0:
            payload[key] = info[key]
    append_event(session, run.id, "runtime.ready", payload)


def retain_ready(session, run, instance, info):
    validate_load(run, instance)
    if isinstance(session, ScopedSession) and (
        not session.scope.execution or session.scope.read_only or session.scope.user_id != run.owner_id
    ):
        raise DataAccessError("Shared model retention requires its owned execution")
    if (
        info.get("instance_id", instance.id) != instance.id
        or info.get("alive") is not True
        or info.get("status") != "ready"
        or not foreign_demand(session, run, instance)
    ):
        return False
    from app.llama import update_instance

    update_instance(session, instance, info)
    run.metadata_json = {
        **run.metadata_json,
        "shared_model_retained": True,
        "cleanup_requires_inspection": False,
    }
    run.summary = "Request canceled; shared model remains available to other accounts"
    record_ready(session, run, instance, info)
    if run.status != RunStatus.CANCEL_REQUESTED:
        transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
    transition(
        session, run, RunStatus.CANCELED, event_type="runtime.retained", payload={"instance_id": instance.id}
    )
    # A terminal user request does not imply that its model's GPUs/RAM are free.
    return True


def cleanup_revoked_stop(session, run, worker_id):
    """A revoked stop may observe completion, but cannot issue a new stop."""
    if isinstance(session, ScopedSession):
        raise DataAccessError("Revoked model cleanup requires trusted queue coordination")
    if run.executor_type != "llama_stop" or run.owner_id is None:
        return False
    user = session.get(User, run.owner_id, populate_existing=True)
    if (
        user is not None
        and user.enabled
        and not user.bootstrap_pending
        and not run.metadata_json.get("cancel_on_resume")
        and run.status != "cancel_requested"
    ):
        return False
    identity, owner = run.id, run.owner_id
    run = session.get(Run, identity, populate_existing=True, with_for_update=True)
    if (
        run is None
        or run.owner_id != owner
        or run.worker_id != worker_id
        or run.status not in {"claimed", "cancel_requested"}
    ):
        session.commit()
        return True
    instance = session.get(RuntimeInstance, run.parameters.get("instance_id"))
    valid = (
        instance is not None
        and instance.ownership == "managed"
        and instance.runtime_key == "llama.cpp"
        and run.capability == "runtime.stop"
        and run.execution_target == "host"
        and "manage_models" in run.effective_permissions
        and run.task.owner_id == owner
        and instance.metadata_json.get("operation_run_id") == identity
    )
    if valid:
        from app.runtime_coordination import runtime_load_facts

        try:
            runtime_load_facts(session, instance)
        except ValueError:
            valid = False
    if not valid:
        run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
        transition(session, run, RunStatus.INTERRUPTED, event_type="recovery.inspection_required")
        session.commit()
        return True
    if run.status != "cancel_requested":
        transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
    instance_id = instance.id
    session.commit()
    try:
        info = RunnerClient(timeout=10).inspect_llama(instance_id)
    except (RunnerError, RunnerUnavailable, ValueError):
        info = None
    run = session.get(Run, identity, populate_existing=True, with_for_update=True)
    instance = session.get(RuntimeInstance, instance_id, populate_existing=True, with_for_update=True)
    if run is None or run.owner_id != owner or run.worker_id != worker_id or run.status != "cancel_requested":
        session.commit()
        return True
    if instance is None or instance.metadata_json.get("operation_run_id") != identity:
        run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
        transition(session, run, RunStatus.INTERRUPTED, event_type="recovery.inspection_required")
        session.commit()
        return True
    if isinstance(info, dict) and info.get("instance_id", instance_id) == instance_id:
        from app.llama import update_instance

        gone = info.get("alive") is False and info.get("status") in ("stopped", "failed")
        if (
            gone
            or not run.metadata_json.get("dispatch_attempted")
            and info.get("alive") is True
            and info.get("status") in ("ready", "loading")
        ):
            update_instance(session, instance, info)
            run.metadata_json = {
                **run.metadata_json,
                "process_confirmed_gone": gone,
                "cleanup_requires_inspection": False,
            }
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            release_run_locks(session, identity)
            session.commit()
            return True
        if info.get("alive") is True and info.get("status") == "stopping":
            update_instance(session, instance, info)
            touch_lease(session, run)
            append_event(session, identity, "recovery.model_cleanup_pending", {})
            session.commit()
            return True
    if info is None:
        touch_lease(session, run)
        run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
        append_event(session, identity, "recovery.model_cleanup_pending", {})
        session.commit()
        return True
    run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
    instance.status = "unknown"
    transition(session, run, RunStatus.INTERRUPTED, event_type="recovery.inspection_required")
    session.commit()
    return True


def cleanup_revoked_load(session, run, worker_id):
    """Trusted recovery may inspect/stop an existing model, never launch one."""
    if isinstance(session, ScopedSession):
        raise DataAccessError("Revoked model cleanup requires trusted queue coordination")
    if run.executor_type != "llama_load" or run.owner_id is None:
        return False
    user = session.get(User, run.owner_id, populate_existing=True)
    canceled = run.status == "cancel_requested" or run.metadata_json.get("cancel_on_resume")
    if user is not None and user.enabled and not user.bootstrap_pending and not canceled:
        return False
    identity, owner = run.id, run.owner_id
    run = session.get(Run, identity, populate_existing=True, with_for_update=True)
    if (
        run is None
        or run.owner_id != owner
        or run.worker_id != worker_id
        or run.status not in {"claimed", "cancel_requested"}
    ):
        session.commit()
        return True
    instance = session.get(RuntimeInstance, run.parameters.get("instance_id"))
    try:
        validate_load(run, instance)
    except ValueError:
        run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
        transition(session, run, RunStatus.INTERRUPTED, event_type="recovery.inspection_required")
        session.commit()
        return True
    if run.status != RunStatus.CANCEL_REQUESTED:
        transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
    run.metadata_json = {**run.metadata_json, "cancel_on_resume": True}
    dispatched = bool(run.metadata_json.get("dispatch_attempted"))
    if not dispatched:
        if instance.status != "queued":
            run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
            transition(session, run, RunStatus.INTERRUPTED, event_type="recovery.inspection_required")
        else:
            instance.status = "stopped"
            run.metadata_json = {
                **run.metadata_json,
                "process_confirmed_gone": True,
                "cleanup_requires_inspection": False,
            }
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            release_run_locks(session, identity)
        session.commit()
        return True
    instance_id = instance.id
    session.commit()
    runner = RunnerClient(timeout=10)
    try:
        info = runner.inspect_llama(instance_id)
    except (RunnerError, RunnerUnavailable, ValueError):
        info = None
    run = session.get(Run, identity, populate_existing=True, with_for_update=True)
    instance = session.get(RuntimeInstance, instance_id, populate_existing=True, with_for_update=True)
    if run is None or run.owner_id != owner or run.worker_id != worker_id or run.status != "cancel_requested":
        session.commit()
        return True
    if quarantine_changed_load(session, run, instance):
        return True
    # Recheck demand after native I/O so a newly waiting account is not stopped
    # based on an earlier empty snapshot. Uncertain inspection cannot authorize stop.
    retain = (
        not run.metadata_json.get("load_shutdown_requested")
        and before_deadline(run)
        and foreign_demand(session, run, instance)
    )
    if isinstance(info, dict) and (info.get("instance_id", instance_id) == instance_id):
        if retain and retain_ready(session, run, instance, info):
            session.commit()
            return True
        if not retain and info.get("alive") is True:
            instance.status = "stopping"
            instance.metadata_json = {**instance.metadata_json, "operation_run_id": run.id}
            run.metadata_json = {**run.metadata_json, "load_shutdown_requested": True}
            session.commit()
            try:
                info = runner.stop_llama(instance_id)
            except (RunnerError, RunnerUnavailable, ValueError):
                info = None
            run = session.get(Run, identity, populate_existing=True, with_for_update=True)
            instance = session.get(RuntimeInstance, instance_id, populate_existing=True, with_for_update=True)
            if (
                run is None
                or run.owner_id != owner
                or run.worker_id != worker_id
                or run.status != "cancel_requested"
            ):
                session.commit()
                return True
            if quarantine_changed_load(session, run, instance):
                return True
        if isinstance(info, dict) and info.get("instance_id", instance_id) == instance_id:
            from app.llama import update_instance

            if info.get("alive") is False and info.get("status") in ("stopped", "failed"):
                update_instance(session, instance, info)
                run.metadata_json = {
                    **run.metadata_json,
                    "process_confirmed_gone": True,
                    "cleanup_requires_inspection": False,
                }
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                return True
            if info.get("alive") is True and info.get("status") in ("loading", "ready", "stopping"):
                update_instance(session, instance, info)
    touch_lease(session, run)
    run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
    append_event(session, identity, "recovery.model_cleanup_pending", {})
    session.commit()
    return True
