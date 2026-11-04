"""Task-wide Stop serialized with child publication in the existing database."""

from fastapi import HTTPException
from sqlalchemy import select

from app.db import utcnow
from app.events import append_event
from app.models import Run, RunDependency, Task
from app.state import TERMINAL


def lock_task(session, task):
    session.execute(select(Task.id).where(Task.id == task.id).with_for_update())
    session.refresh(task, ["metadata_json"])


def cancel_task(session, task):
    from app.runs import request_cancel
    from app.runtime_coordination import shared_load_in_use

    lock_task(session, task)
    active = list(
        session.scalars(select(Run).where(Run.task_id == task.id, Run.status.not_in(TERMINAL)).limit(1025))
    )
    if len(active) > 1024:
        raise HTTPException(409, "Task graph exceeds the cancellation bound; inspect its Runs")
    task.metadata_json = {**task.metadata_json, "stop_requested_at": utcnow().isoformat()}
    canceled = []
    retained = []
    for run in active:
        if run.status in TERMINAL:
            # Stopping a parent can already have canceled its owned child.
            if run.status == "canceled":
                canceled.append(run.id)
            continue
        # Model startup may be shared by conversations outside this Task.
        # Stopping its original consumer must not break their prerequisite.
        if (
            run.executor_type == "llama_load"
            or run.executor_type == "llama_stop"
            and run.parameters.get("evicted_for_run_id")
        ) and (
            shared_load_in_use(session, run)
            or session.scalar(
                select(Run.id)
                .join(RunDependency, RunDependency.run_id == Run.id)
                .where(
                    RunDependency.prerequisite_id == run.id,
                    Run.task_id != task.id,
                    Run.status.not_in(TERMINAL),
                )
                .limit(1)
            )
        ):
            append_event(session, run.id, "task.stop_shared_runtime_retained", {"task_id": task.id})
            retained.append(run.id)
            continue
        if run.status != "cancel_requested":
            request_cancel(session, run)
        append_event(session, run.id, "task.stop_requested", {"task_id": task.id})
        canceled.append(run.id)
    forwarded = []
    if task.intent == "agent.control":
        # A Stop may arrive just after the short controller atomically published
        # its separate background workflow. Forward only to that owned execution;
        # an already-running/busy receipt grants no ownership of someone else's job.
        for controller in session.scalars(
            select(Run).where(Run.task_id == task.id, Run.executor_type == "agent_control")
        ):
            result = controller.metadata_json.get("agent_control_result") or {}
            scope = controller.parameters.get("scope") or {}
            if not isinstance(result, dict) or not isinstance(scope, dict):
                continue
            child_id = result.get("workflow_run_id")
            child = session.get(Run, child_id) if isinstance(child_id, str) else None
            if not (
                task.conversation_id is not None
                and controller.conversation_id == task.conversation_id
                and controller.status == "succeeded"
                and result.get("outcome") == "queued"
                and result.get("operation") == scope.get("operation") == "run"
                and child
                and child.executor_type == "agent_workflow"
                and child.task_id != task.id
                and child.task.agent_id == child.agent_id
                and child.task_id == result.get("task_id")
                and child.agent_id == result.get("agent_id") == scope.get("agent_id")
                and child.metadata_json.get("conversation_control_run_id") == controller.id
                and child.task.metadata_json.get("conversation_control_run_id") == controller.id
                and child.task.metadata_json.get("originating_conversation_id") == task.conversation_id
                and session.scalar(
                    select(Run.id).where(Run.task_id == child.task_id, Run.status.not_in(TERMINAL)).limit(1)
                )
            ):
                continue
            stopped = cancel_task(session, child.task)
            forwarded.append(child.task_id)
            canceled.extend(stopped["run_ids"])
            retained.extend(stopped["retained_run_ids"])
            append_event(session, controller.id, "agent.control.stop_forwarded", {"task_id": child.task_id})
    session.flush()
    return {
        "task_id": task.id,
        "stop_requested": True,
        "run_ids": canceled,
        "retained_run_ids": retained,
        **({"agent_task_ids": forwarded} if forwarded else {}),
    }


def stopped_task(session, task):
    lock_task(session, task)
    return bool(task.metadata_json.get("stop_requested_at"))
