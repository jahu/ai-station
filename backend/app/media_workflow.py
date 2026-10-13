"""Read-only traversal of owned sequential media steps."""

from fastapi import HTTPException

from app.models import Run
from app.redact import redact_obj
from app.runs import run_dict


def workflow_steps(session, run_id, executors):
    current = session.get(Run, str(run_id))
    if current is None or current.executor_type not in executors:
        raise HTTPException(404, "Media Run not found")
    task_id = current.task_id
    steps = []
    seen = set()
    while current is not None:
        if current.id in seen or len(steps) >= 40:
            raise HTTPException(409, "Media workflow needs inspection")
        seen.add(current.id)
        steps.append(run_dict(current))
        next_id = next(
            (
                current.metadata_json.get(key)
                for key in ("upscale_run_id", "video_run_id", "avatar_run_id", "retry_run_id")
                if current.metadata_json.get(key)
            ),
            None,
        )
        if not next_id:
            break
        child = session.get(Run, next_id)
        if (
            child is None
            or child.parent_run_id != current.id
            or child.task_id != task_id
            or child.executor_type not in executors
        ):
            raise HTTPException(409, "Media workflow needs inspection")
        current = child
    return redact_obj({"steps": steps})
