"""Provision an owned project before dispatching a project-free Local coding agent."""

from datetime import datetime, timedelta
from uuid import UUID

from app.agent_coding_policy import coding_provider
from app.agent_schema import AgentSettings
from app.agent_tools import effective_permissions
from app.db import utcnow
from app.events import append_event
from app.models import Agent, Run
from app.permissions import require
from app.project_checks import project_check_policy
from app.project_setup import ProjectName, enqueue_project
from app.runs import create_run, mark_failed, transition
from app.state import RunStatus


def coding_deadline(parent, definition):
    raw = parent.parameters.get("agent_coding_deadline")
    deadline = (
        datetime.fromisoformat(raw)
        if raw
        else ((parent.started_at or utcnow()) + timedelta(seconds=definition.maximum_runtime))
    )
    if deadline <= utcnow():
        raise ValueError("Agent runtime limit exceeded before workspace/coding dispatch")
    return deadline


def publish_workspace(session, parent, definition, deadline):
    if coding_provider(definition.tools) != "local" or definition.project_id or parent.project_id:
        raise ValueError("Automatic workspaces require a project-free Local coding agent")
    for permission in effective_permissions(definition.tools):
        require(parent.effective_permissions, permission)
    with session.begin_nested():
        child = enqueue_project(
            session, ProjectName(name=definition.name), task=parent.task, parent_run_id=parent.id
        )
        parent.task.metadata_json = {
            **parent.task.metadata_json,
            "agent_coding_definition": definition.model_dump(mode="json"),
        }
        parent.metadata_json = {**parent.metadata_json, "workspace_setup_run_id": child.id}
        child.triggered_by = parent.triggered_by
        child.parameters = {
            **child.parameters,
            "agent_workspace": {"root_run_id": parent.id},
            "agent_coding_deadline": deadline.isoformat(),
        }
        append_event(session, parent.id, "agent.workspace.requested", {"run_id": child.id})
    return child


def reviewed_workspace(session, run):
    """Verify the frozen root before adopting a native project or publishing work."""
    marker = run.parameters.get("agent_workspace")
    parent = session.get(Run, marker.get("root_run_id")) if isinstance(marker, dict) else None
    if (
        parent is None
        or parent.executor_type != "agent_workflow"
        or parent.status != "succeeded"
        or run.parent_run_id != parent.id
        or run.task_id != parent.task_id
        or run.agent_id != parent.agent_id
        or run.project_id is not None
        or parent.project_id is not None
        or run.task.project_id is not None
        or run.parameters.get("agent_coding_deadline") != parent.parameters.get("agent_coding_deadline")
    ):
        raise ValueError("Workspace does not belong to the exact reviewed agent workflow")
    definition = AgentSettings.model_validate(parent.parameters["definition"])
    agent = session.get(Agent, parent.agent_id)
    if (
        agent is None
        or coding_provider(definition.tools) != "local"
        or definition.project_id is not None
        or AgentSettings.model_validate(
            {key: getattr(agent, key) for key in AgentSettings.model_fields} | {"enabled": False}
        ).model_dump(mode="json")
        != definition.model_dump(mode="json")
    ):
        raise ValueError("The reviewed agent definition changed before workspace creation")
    for permission in effective_permissions(definition.tools):
        require(parent.effective_permissions, permission)
    for permission in ("workspace_write", "git_write"):
        require(run.effective_permissions, permission)
    expected = ProjectName(name=definition.name)
    if (
        run.parameters["settings"]["name"] != expected.name
        or run.parameters["settings"].get("auto_install_dependencies") is not False
        or run.parameters["settings"].get("auto_validate") is not False
    ):
        raise ValueError("Automatic workspace preparation must retain its reviewed offline policy")
    return parent, definition, agent


def finish_workspace(session, run, project, context):
    parent, definition, agent = context
    agent.project_id = project.id
    agent.updated_at = utcnow()
    run.project_id = parent.project_id = run.task.project_id = project.id
    run.metadata_json = {**run.metadata_json, "agent_workspace_project_id": project.id}
    append_event(session, parent.id, "agent.workspace.created", {"project_id": project.id, "run_id": run.id})
    try:
        deadline = coding_deadline(parent, definition)
    except ValueError as exc:
        mark_failed(session, run, "AgentRuntimeLimit", str(exc))
        return "done"
    derived = definition.model_copy(update={"project_id": UUID(project.id)}).model_dump(mode="json")
    transition(
        session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={"project_id": project.id}
    )
    child = create_run(
        session,
        run.task,
        run_type="agent",
        capability="agent.workflow",
        executor_type="agent_workflow",
        execution_target="container",
        parameters={
            "definition": derived,
            **(
                {"data_inputs": parent.parameters["data_inputs"]}
                if "data_inputs" in parent.parameters
                else {}
            ),
            "workspace_source_run_id": run.id,
            "workspace_root_run_id": parent.id,
            "agent_coding_deadline": deadline.isoformat(),
            "coding_project_policy": project_check_policy(project),
            "endpoint": parent.parameters.get("endpoint"),
            "skill_snapshots": parent.parameters.get("skill_snapshots") or [],
        },
        permissions=list(parent.effective_permissions),
        parent_run_id=run.id,
        retry_class="inspect",
        triggered_by=parent.triggered_by,
    )
    run.metadata_json = {**run.metadata_json, "workspace_workflow_run_id": child.id}
    run.summary = "Private agent workspace created; Local coding queued."
    return "done"


def validate_workspace_binding(session, run):
    source_id = run.parameters.get("workspace_source_run_id")
    if source_id is None:
        parent = session.get(Run, run.parent_run_id) if run.parent_run_id else None
        if parent is not None and "agent_workspace" in parent.parameters:
            raise ValueError("Automatic workspace workflow is missing its verified binding")
        return
    source = session.get(Run, source_id)
    root = session.get(Run, run.parameters.get("workspace_root_run_id"))
    if (
        source is None
        or root is None
        or root.executor_type != "agent_workflow"
        or root.status != "succeeded"
        or root.parameters.get("definition", {}).get("project_id") is not None
        or source.executor_type != "project_setup"
        or source.status != "succeeded"
        or source.parent_run_id != root.id
        or run.parent_run_id != source.id
        or source.task_id != run.task_id
        or root.task_id != run.task_id
        or source.agent_id != run.agent_id
        or root.agent_id != run.agent_id
        or not run.project_id
        or source.project_id != run.project_id
        or root.project_id != run.project_id
        or source.parameters.get("project_id") != run.project_id
        or source.parameters.get("agent_workspace") != {"root_run_id": root.id}
        or source.metadata_json.get("workspace_workflow_run_id") != run.id
        or run.parameters.get("definition")
        != {**root.parameters.get("definition", {}), "project_id": run.project_id}
        or run.parameters.get("agent_coding_deadline") != root.parameters.get("agent_coding_deadline")
        or source.parameters.get("agent_coding_deadline") != root.parameters.get("agent_coding_deadline")
        or not set(run.effective_permissions) <= set(root.effective_permissions)
        or run.parameters.get("skill_snapshots") != (root.parameters.get("skill_snapshots") or [])
        or run.parameters.get("data_inputs") != root.parameters.get("data_inputs")
    ):
        raise ValueError("Agent workspace binding changed after verified project creation")


def workspace_retry_definition(session, source, definition):
    """A manual retry may reuse only the project adopted by this exact root."""
    if (
        coding_provider(definition.tools) != "local"
        or definition.project_id is not None
        or source.project_id is None
    ):
        return definition
    setup = session.get(Run, source.metadata_json.get("workspace_setup_run_id"))
    if (
        coding_provider(definition.tools) != "local"
        or setup is None
        or setup.executor_type != "project_setup"
        or setup.status not in {"succeeded", "failed"}
        or setup.parent_run_id != source.id
        or setup.task_id != source.task_id
        or setup.agent_id != source.agent_id
        or setup.project_id != source.project_id
        or setup.parameters.get("agent_workspace") != {"root_run_id": source.id}
        or setup.metadata_json.get("agent_workspace_project_id") != source.project_id
        or setup.parameters.get("project_id") != source.project_id
    ):
        raise ValueError("Retry cannot bind an unverified automatic agent workspace")
    return definition.model_copy(update={"project_id": UUID(source.project_id)})
