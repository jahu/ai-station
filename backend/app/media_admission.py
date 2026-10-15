"""Short, Task-scoped resource deferral; never a permission or replay grant."""

from datetime import timedelta

from app.config import get_settings
from app.db import utcnow
from app.models import Task
from app.resources import RESOURCE_WAIT_KEY as WAIT_KEY
from app.task_control import lock_task


def shot_task(session, run):
    if run.executor_type != "wan_video" or not run.parameters.get("internal_media"):
        return None
    task = session.get(Task, run.task_id)
    if not task or task.metadata_json.get("media_plan", {}).get("mode") != "shots":
        return None
    lock_task(session, task)
    plan = task.metadata_json.get("media_plan", {})
    if (
        plan.get("kind") != "video"
        or plan.get("mode") != "shots"
        or run.id not in plan.get("segment_run_ids", [])
    ):
        return None
    return task


def defer_media_task(session, run):
    task = shot_task(session, run)
    if task is None:
        return True
    if task.metadata_json.get("stop_requested_at"):
        # A Stop may have committed between resource inspection and requeue.
        from app.runs import request_cancel

        session.refresh(run)
        request_cancel(session, run)
        return False
    until = utcnow() + timedelta(seconds=max(2, get_settings().heartbeat_seconds * 2))
    task.metadata_json = {**task.metadata_json, WAIT_KEY: until.isoformat()}
    return True
