"""Agent project work delegates to the existing isolated Local Coding workflow."""

from datetime import timedelta

from fastapi import HTTPException

from app.agent_coding_policy import coding_provider
from app.coding_tasks import CodingTask, enqueue_coding_task
from app.db import utcnow
from app.events import append_event
from app.local_coding import LocalCodingTask
from app.models import Project
from app.skills import skill_prompt, verify_snapshots


def publish_coding(session, parent, definition, *, context="", deadline_at=None, context_sources=None):
    provider = coding_provider(definition.tools)
    if provider is None or not definition.project_id:
        raise ValueError("Select one coding provider and choose its project")
    if parent.project_id != str(definition.project_id):
        raise ValueError("The agent cannot change its authorized project")
    project = session.get(Project, parent.project_id)
    if project is None:
        raise HTTPException(422, "The coding agent's project is no longer available")
    snapshots = verify_snapshots(parent.parameters.get("skill_snapshots") or [])
    with session.begin_nested():
        deadline = deadline_at or (utcnow() + timedelta(seconds=definition.maximum_runtime))
        if deadline <= utcnow():
            raise ValueError("Agent runtime limit exceeded before coding publication")
        deadline = deadline.isoformat()
        parent.task.metadata_json = {
            **parent.task.metadata_json,
            "agent_coding_definition": definition.model_dump(mode="json"),
        }
        body_type = LocalCodingTask if provider == "local" else CodingTask
        request_key = "local_coding" if provider == "local" else provider
        preparation = enqueue_coding_task(
            session,
            body_type(
                project_id=project.id,
                expected_updated_at=project.updated_at,
                prompt=definition.goal,
                model=definition.model if provider == "local" else "",
                explore=True,
            ),
            provider=provider,
            task=parent.task,
            parent_run_id=parent.id,
            workflow_parent=parent,
        )
        request = preparation.parameters[request_key]
        preparation.parameters = {**preparation.parameters, "agent_coding_deadline": deadline}
        guidance = definition.system_prompt + "\n" + request["guidance"]
        output_fields = {}
        if request["project_check_policy"]["auto_validate"]:
            from app.coding_output import website_output

            contract = website_output(definition.goal)
            if contract:
                output_fields["output_contract"] = contract
                guidance += "\nThe website build must write a nonempty dist/index.html and its local assets for the verified preview/download."
            guidance += (
                "\nThis agent's reviewed new-workspace policy runs detected checks/builds. "
                "For a website, create a complete self-contained static site with package.json "
                "test/build scripts and output under dist/. Declare any required public-registry "
                "dependencies in the manifest; avoid runtime CDN dependencies. Do not modify "
                "saved project validation policy or claim checks passed before actual execution."
            )
        if snapshots:
            guidance += "\n" + skill_prompt(snapshots)
        if context:
            if provider != "local" or len(context) > 10000:
                raise ValueError("Reviewed page context must be bounded and use Local coding")
            guidance += "\n" + context
        if len(guidance) > 16000:
            raise ValueError("Agent and project guidance exceed the coding context limit")
        preparation.parameters = {
            **preparation.parameters,
            request_key: {
                **request,
                **output_fields,
                "guidance": guidance,
                **(
                    {"max_repair_attempts": 1 if request["project_check_policy"]["auto_validate"] else 0}
                    if provider == "local"
                    else {}
                ),
                **({"context_sources": context_sources} if context_sources else {}),
                "agent_coding_deadline": deadline,
            },
        }
        if provider == "local" and request["project_check_policy"]["auto_validate"]:
            append_event(
                session,
                preparation.id,
                "coding.repair.policy",
                {"maximum_attempts": 1, "source": "agent_automatic_checks", "deadline_at": deadline},
            )
        preparation.triggered_by = parent.triggered_by
        return preparation
