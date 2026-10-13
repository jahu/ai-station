"""Task and run services: transitions, claiming, cancel, retry."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, aliased

from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.models import Agent, Run, RunDependency, Task
from app.state import TERMINAL, InvalidTransition, RunStatus, assert_transition


def create_task(
    session: Session,
    *,
    title: str,
    prompt: str,
    capability: str,
    intent: str = "",
    project_id: str | None = None,
    conversation_id: str | None = None,
    agent_id: str | None = None,
    metadata: dict | None = None,
) -> Task:
    task = Task(
        title=title[:300],
        prompt=prompt,
        capability=capability,
        intent=intent,
        project_id=project_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        metadata_json=metadata or {},
        status="open",
    )
    session.add(task)
    session.flush()
    return task


def create_run(
    session: Session,
    task: Task,
    *,
    run_type: str,
    capability: str,
    executor_type: str,
    execution_target: str = "host",
    parameters: dict | None = None,
    requested_resources: dict | None = None,
    requested_gpu: str = "none",
    permissions: list[str] | None = None,
    retry_class: str = "inspect",
    triggered_by: str = "user",
    project_id: str | None = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
    parent_run_id: str | None = None,
    metadata: dict | None = None,
) -> Run:
    now = utcnow()
    run = Run(
        task_id=task.id,
        run_type=run_type,
        capability=capability,
        executor_type=executor_type,
        execution_target=execution_target,
        status=RunStatus.QUEUED.value,
        queued_at=now,
        parameters=parameters or {},
        requested_resources=requested_resources or {},
        requested_gpu=requested_gpu,
        effective_permissions=permissions or [],
        retry_class=retry_class,
        triggered_by=triggered_by,
        project_id=project_id if project_id is not None else task.project_id,
        agent_id=agent_id if agent_id is not None else task.agent_id,
        conversation_id=conversation_id if conversation_id is not None else task.conversation_id,
        parent_run_id=parent_run_id,
        metadata_json=metadata or {},
    )
    session.add(run)
    session.flush()
    append_event(session, run.id, "run.created", {"capability": capability, "executor": executor_type})
    return run


def transition(
    session: Session, run: Run, target: str, *, event_type: str, payload: dict | None = None
) -> Run:
    # Refresh after any external operation so cancellation cannot be overwritten
    # by an executor holding a stale ORM instance.
    session.refresh(run, attribute_names=["status"])
    assert_transition(run.status, target)
    now = utcnow()
    run.status = target
    if target == RunStatus.CLAIMED:
        run.claimed_at = now
    elif target == RunStatus.RUNNING and run.started_at is None:
        run.started_at = now
    elif target == RunStatus.CANCEL_REQUESTED:
        run.cancellation_requested_at = now
    elif target in {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELED,
        RunStatus.INTERRUPTED,
    }:
        run.finished_at = now
    if run.agent_id:
        agent = session.get(Agent, run.agent_id)
        if agent is not None and not (
            run.executor_type == "agent_workflow" and target == RunStatus.SUCCEEDED
        ):
            agent.last_status = target
            if run.executor_type != "agent_tool":
                if target in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
                    agent.failure_count += 1
                elif target == RunStatus.SUCCEEDED:
                    agent.failure_count = 0
    append_event(session, run.id, event_type, payload or {"status": target})
    session.flush()
    from app.connectors import sync_connector_from_run
    from app.notices import emit_agent_notice

    emit_agent_notice(session, run, target)
    sync_connector_from_run(session, run, target)
    return run


def claim_next(session: Session, worker_id: str) -> Run | None:
    settings = get_settings()
    now = utcnow()
    prerequisite = aliased(Run)
    blocked = (
        select(RunDependency.run_id)
        .join(prerequisite, prerequisite.id == RunDependency.prerequisite_id)
        .where(prerequisite.status.not_in(TERMINAL))
    )
    candidate = session.scalar(
        select(Run)
        .where(Run.status == RunStatus.QUEUED.value, Run.id.not_in(blocked))
        .order_by(Run.queued_at, Run.created_at)
        .limit(1)
    )
    if candidate is None:
        return None
    lease = now + timedelta(seconds=settings.lease_seconds)
    result = session.execute(
        update(Run)
        .where(Run.id == candidate.id, Run.status == RunStatus.QUEUED.value)
        .values(
            status=RunStatus.CLAIMED.value,
            worker_id=worker_id,
            claimed_at=now,
            lease_expires_at=lease,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        return None
    session.flush()
    session.refresh(candidate)
    append_event(session, candidate.id, "run.claimed", {"worker_id": worker_id})
    return candidate


def touch_lease(session: Session, run: Run) -> None:
    settings = get_settings()
    run.lease_expires_at = utcnow() + timedelta(seconds=settings.lease_seconds)
    session.flush()


def mark_failed(session: Session, run: Run, error_type: str, message: str) -> None:
    run.error_type = error_type[:120]
    run.error_message = message[:4000]
    if run.status == RunStatus.CANCEL_REQUESTED:
        transition(session, run, RunStatus.FAILED, event_type="run.failed", payload={"error": message})
        return
    try:
        transition(session, run, RunStatus.FAILED, event_type="run.failed", payload={"error": message})
    except InvalidTransition:
        if run.status not in TERMINAL:
            raise


def request_cancel(session: Session, run: Run) -> Run:
    if run.status == RunStatus.CANCEL_REQUESTED:
        return run
    if run.executor_type == "agent_workflow" and run.status in TERMINAL:
        from app.agent_workflow import active_workflow_child

        child = active_workflow_child(session, run)
        if child is not None:
            return request_cancel(session, child)
    if run.status in TERMINAL and (
        run.executor_type == "photo_pipe"
        and run.parameters.get("upscale_result")
        or run.executor_type == "chatterbox"
        and run.parameters.get("avatar_after_speech")
    ):
        from app.media_workflow import workflow_steps

        executors = {"photo_pipe"} if run.executor_type == "photo_pipe" else {"chatterbox", "echomimic"}
        steps = workflow_steps(session, run.id, executors)["steps"]
        child = session.get(Run, steps[-1]["id"])
        if child.id != run.id and child.status not in TERMINAL:
            return request_cancel(session, child)
    run.cancellation_requested_at = utcnow()
    if (
        run.status == RunStatus.QUEUED
        and run.executor_type in {"llama_load", "llama_stop"}
        and run.metadata_json.get("dispatch_attempted")
    ):
        # A resumed lifecycle operation may still own a container. Let the next
        # claim confirm its stop instead of declaring a queued run canceled.
        run.metadata_json = {**run.metadata_json, "cancel_on_resume": True}
        append_event(session, run.id, "run.cancel_requested", {"awaiting_owned_runtime_stop": True})
        session.flush()
        return run
    if run.status in {RunStatus.QUEUED.value}:
        return transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
    if run.status in {RunStatus.CLAIMED.value, RunStatus.PREPARING.value, RunStatus.RUNNING.value}:
        return transition(
            session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested", payload={}
        )
    if run.status == RunStatus.WAITING_FOR_APPROVAL:
        from app.approvals import dismiss_pending

        dismiss_pending(session, run)
        return transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
    raise InvalidTransition(run.status, RunStatus.CANCEL_REQUESTED.value)


def run_dict(run: Run) -> dict[str, Any]:
    def iso(value):
        return value.isoformat() if value else None

    return {
        "id": run.id,
        "task_id": run.task_id,
        "run_type": run.run_type,
        "capability": run.capability,
        "executor_type": run.executor_type,
        "execution_target": run.execution_target,
        "status": run.status,
        "created_at": iso(run.created_at),
        "queued_at": iso(run.queued_at),
        "claimed_at": iso(run.claimed_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
        "requested_resources": run.requested_resources,
        "allocated_resources": run.allocated_resources,
        "requested_gpu": run.requested_gpu,
        "actual_gpu": run.actual_gpu,
        "parameters": run.parameters,
        "project_id": run.project_id,
        "agent_id": run.agent_id,
        "conversation_id": run.conversation_id,
        "parent_run_id": run.parent_run_id,
        "worker_id": run.worker_id,
        "runner_id": run.runner_id,
        "pid": run.pid,
        "process_group_id": run.process_group_id,
        "stdout_log": run.stdout_log,
        "stderr_log": run.stderr_log,
        "error_type": run.error_type,
        "error_message": run.error_message,
        "cancellation_requested_at": iso(run.cancellation_requested_at),
        "triggered_by": run.triggered_by,
        "metadata": run.metadata_json,
        "effective_permissions": run.effective_permissions,
        "lease_expires_at": iso(run.lease_expires_at),
        "retry_class": run.retry_class,
        "summary": run.summary,
    }
