"""Agent project work delegates to the existing isolated Local Coding workflow."""

from datetime import timedelta

from fastapi import HTTPException

from app.coding_tasks import enqueue_coding_task
from app.db import utcnow
from app.local_coding import LocalCodingTask
from app.models import Project
from app.skills import skill_prompt, verify_snapshots


def publish_coding(session, parent, definition):
    if definition.tools != ["coding_local"] or not definition.project_id:
        raise ValueError("Select Local coding alone and choose its project")
    if parent.project_id != str(definition.project_id):
        raise ValueError("The agent cannot change its authorized project")
    project = session.get(Project, parent.project_id)
    if project is None:
        raise HTTPException(422, "The coding agent's project is no longer available")
    snapshots = verify_snapshots(parent.parameters.get("skill_snapshots") or [])
    with session.begin_nested():
        deadline = (utcnow() + timedelta(seconds=definition.maximum_runtime)).isoformat()
        parent.task.metadata_json = {
            **parent.task.metadata_json,
            "agent_coding_definition": definition.model_dump(mode="json"),
        }
        preparation = enqueue_coding_task(
            session,
            LocalCodingTask(
                project_id=project.id,
                expected_updated_at=project.updated_at,
                prompt=definition.goal,
                model=definition.model,
                explore=True,
            ),
            provider="local",
            task=parent.task,
            parent_run_id=parent.id,
            workflow_parent=parent,
        )
        request = preparation.parameters["local_coding"]
        preparation.parameters = {**preparation.parameters, "agent_coding_deadline": deadline}
        guidance = definition.system_prompt + "\n" + request["guidance"]
        if snapshots:
            guidance += "\n" + skill_prompt(snapshots)
        if len(guidance) > 16000:
            raise ValueError("Agent and project guidance exceed the coding context limit")
        preparation.parameters = {
            **preparation.parameters,
            "local_coding": {
                **request,
                "guidance": guidance,
                "agent_coding_deadline": deadline,
            },
        }
        preparation.triggered_by = parent.triggered_by
        return preparation
