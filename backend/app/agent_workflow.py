"""Publish persisted agent steps as ordinary child Runs with dependencies."""

from __future__ import annotations

import json
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.agent_coding_policy import coding_provider, coding_research_steps
from app.agent_schema import AgentSettings
from app.agent_tools import RETENTION_TOOLS, WORKFLOW_MEMORY_TOOLS, agent_tool, execution_permissions
from app.artifacts import register_file
from app.db import utcnow
from app.dependencies import depend_on
from app.events import append_event
from app.models import Artifact, Run
from app.runs import create_run, mark_failed, transition
from app.state import ACTIVE, RunStatus

CONTEXT_STEPS = frozenset(
    {
        "system_snapshot",
        "memory_search",
        "project_memory",
        "web_search",
        "search_pages",
        "http_fetch",
        "browser",
        "github_read",
    }
)
STEP_KEYS = CONTEXT_STEPS | {"report", "create_media"}


def planned_steps(definition: AgentSettings) -> list[dict]:
    if definition.tools == ["market_watch"]:
        from app.market_watch import STEPS

        return [{"key": key, "gate": "none"} for key in STEPS]
    if coding_provider(definition.tools) is not None:
        return (
            [{"key": "workspace.create", "gate": "none"}]
            if coding_provider(definition.tools) == "local" and not definition.project_id
            else []
        ) + [
            {"key": name, "gate": "none"}
            for name in (
                coding_research_steps(definition.tools)
                + ["python_data" if "python_data" in definition.tools else "coding_local"]
                if coding_research_steps(definition.tools)
                else definition.tools
            )
        ]
    steps = []
    tools = list(definition.tools)
    if "search_pages" in tools:
        tools.remove("search_pages")
        tools.insert(tools.index("web_search") + 1, "search_pages")
    for name in tools:
        if name in RETENTION_TOOLS:
            continue
        if name == "create_media":
            continue
        if name not in CONTEXT_STEPS or not agent_tool(name).operational:
            raise ValueError(f"Refusing an invented or unavailable agent step: {name}")
        steps.append({"key": name, "gate": "none"})
    steps.append(
        {
            "key": "create_media" if definition.media else "report",
            "gate": "approval" if definition.workflow_mode == "gated" else "none",
        }
    )
    return steps


def workflow_parent(session, run):
    visited = set()
    while run is not None and run.id not in visited and len(visited) < 100:
        if run.executor_type == "agent_workflow":
            return run
        visited.add(run.id)
        run = session.get(Run, run.parent_run_id) if run.parent_run_id else None
    return None


def workflow_view(session, run: Run) -> dict | None:
    parent = workflow_parent(session, run)
    if parent is None:
        return None
    children = [
        child
        for child in session.scalars(
            select(Run).where(Run.parent_run_id == parent.id).order_by(Run.created_at, Run.id)
        )
        if child.executor_type in {"agent_tool", "agent", "browser", "github_read", "agent_market"}
    ]
    definition = parent.parameters.get("definition") or {}
    if (
        coding_provider(definition.get("tools", [])) is not None
        or definition.get("media") is not None
        or (definition.get("notification_policy") or {}).get("report_email")
        or definition.get("tools") == ["market_watch"]
        and (definition.get("market") or {}).get("email")
    ):
        children = list(
            session.scalars(
                select(Run)
                .where(Run.task_id == parent.task_id, Run.id != parent.id)
                .order_by(Run.created_at, Run.id)
            )
        )
    return {
        "parent_run_id": parent.id,
        "mode": definition.get("workflow_mode", "sequential"),
        "tool_calling": definition.get("tool_calling", "none"),
        "steps": [
            {
                "run_id": child.id,
                "key": child.capability
                if coding_provider(definition.get("tools", [])) is not None
                or definition.get("media") is not None
                else child.parameters.get("tool") or "report",
                "gate": child.parameters.get("gate", "none"),
                "status": child.status,
                "capability": child.capability,
                "tool_calls": child.metadata_json.get("tool_calls") or [],
                "memory_id": child.metadata_json.get("memory_entry_id"),
                "memory_excerpted": child.metadata_json.get("memory_excerpted") is True,
            }
            for child in children
        ],
    }


def active_workflow_child(session, run: Run) -> Run | None:
    parent = workflow_parent(session, run)
    if parent is None:
        return None
    children = [
        child
        for child in session.scalars(select(Run).where(Run.parent_run_id == parent.id))
        if child.status in ACTIVE
    ]
    if (
        coding_provider(parent.parameters.get("definition", {}).get("tools", [])) is not None
        or parent.parameters.get("definition", {}).get("media") is not None
        or (parent.parameters.get("definition", {}).get("notification_policy") or {}).get("report_email")
    ):
        children = list(
            session.scalars(
                select(Run).where(Run.task_id == parent.task_id, Run.id != parent.id, Run.status.in_(ACTIVE))
            )
        )
    rank = {
        RunStatus.RUNNING.value: 0,
        RunStatus.CLAIMED.value: 1,
        RunStatus.PREPARING.value: 2,
        RunStatus.CANCEL_REQUESTED.value: 3,
        RunStatus.WAITING_FOR_APPROVAL.value: 4,
        RunStatus.QUEUED.value: 5,
    }
    children.sort(key=lambda child: (rank.get(child.status, 9), child.created_at, child.id))
    return children[0] if children else None


def sibling_context(session, run: Run) -> list[dict]:
    if not run.parent_run_id:
        raise ValueError("Agent report is missing its workflow parent")
    siblings = list(
        session.scalars(
            select(Run)
            .where(Run.parent_run_id == run.parent_run_id, Run.capability == "agent.step")
            .order_by(Run.created_at, Run.id)
        )
    )
    context = []
    for sibling in siblings:
        if sibling.status != RunStatus.SUCCEEDED.value:
            raise ValueError("Refusing to generate a report from an incomplete workflow step")
        tool = sibling.parameters.get("tool")
        if tool not in CONTEXT_STEPS:
            raise ValueError(f"Refusing an invented workflow observation: {tool}")
        result = sibling.metadata_json.get("observation")
        if result is None:
            artifact = session.scalar(
                select(Artifact)
                .where(Artifact.run_id == sibling.id, Artifact.artifact_type == "json")
                .order_by(Artifact.created_at.desc())
            )
            if artifact is None:
                raise ValueError("Workflow step is missing its observation artifact")
            from app.config import get_settings
            from app.paths import safe_join

            result = json.loads(safe_join(get_settings().data_dir, artifact.relative_path).read_text())
        if tool == "github_read":
            from app.agent_github import report_context

            result = report_context(result)
        context.append({"tool": tool, "result": result})
    return context


class AgentWorkflowExecutor:
    name = "agent_workflow"

    def execute(self, session, run):
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        try:
            children = publish_steps(session, run)
        except Exception as exc:
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return "done"
            mark_failed(session, run, type(exc).__name__, str(exc) or "Workflow could not be published")
            return "done"
        run.metadata_json = {
            **run.metadata_json,
            "workflow_mode": (run.parameters.get("definition") or {}).get("workflow_mode", "sequential"),
            "child_run_ids": [child.id for child in children],
        }
        run.summary = f"Published {len(children)} workflow step{'s' if len(children) != 1 else ''}."
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload=run.metadata_json)
        session.commit()
        return "done"


def publish_steps(session, parent: Run) -> list[Run]:
    definition = AgentSettings.model_validate(parent.parameters["definition"])
    if "python_data" in definition.tools and parent.agent_id is None:
        from app.conversation_data import validate_workflow

        validate_workflow(session, parent)
    if definition.tools == ["market_watch"]:
        from app.market_watch import publish_market_steps

        return publish_market_steps(session, parent, definition)
    github_target = None
    if "github_read" in definition.tools:
        from app.agent_github import reviewed_connector

        github_target = reviewed_connector(session, definition.github)
    if coding_provider(definition.tools) is not None:
        from app.agent_workspace import coding_deadline, publish_workspace, validate_workspace_binding

        validate_workspace_binding(session, parent)
        deadline = coding_deadline(parent, definition)
        parent.parameters = {**parent.parameters, "agent_coding_deadline": deadline.isoformat()}
        if "python_data" in definition.tools:
            from app.data_agents import require_runtime, verify_inputs

            require_runtime()
            verify_inputs(
                session,
                parent.parameters.get("data_inputs"),
                allow_empty=bool(coding_research_steps(definition.tools)),
            )
        if coding_provider(definition.tools) == "local" and not definition.project_id:
            return [publish_workspace(session, parent, definition, deadline)]
        if coding_research_steps(definition.tools):
            from app.agent_page_coding import publish_page_coding

            return publish_page_coding(session, parent, definition, deadline_at=deadline)
        if "python_data" in definition.tools:
            from app.data_agents import publish_data

            return [publish_data(session, parent, definition, deadline)]
        from app.agent_coding import publish_coding

        return [publish_coding(session, parent, definition, deadline_at=deadline)]
    steps = parent.parameters.get("steps")
    if not isinstance(steps, list) or not steps:
        steps = planned_steps(definition)
    allowed = {name for name in definition.tools if name not in RETENTION_TOOLS} | {"report"}
    deadline_at = ((parent.started_at or utcnow()) if definition.media else utcnow()) + timedelta(
        seconds=definition.maximum_runtime
    )
    if definition.media:
        parent.parameters = {**parent.parameters, "media_deadline_at": deadline_at.isoformat()}
    validated = []
    for index, raw in enumerate(steps):
        if not isinstance(raw, dict):
            raise ValueError("Workflow steps must be objects")
        key = raw.get("key")
        gate = raw.get("gate", "none")
        if key not in STEP_KEYS or key not in allowed or gate not in {"none", "approval"}:
            raise ValueError(f"Refusing an invented or unauthorized workflow step: {key}")
        if key != "report" and (
            key not in CONTEXT_STEPS | {"create_media"} or not agent_tool(key).operational
        ):
            raise ValueError(f"Refusing an invented or unavailable agent step: {key}")
        validated.append((index, key, gate))
    created: list[Run] = []
    previous = None
    for index, key, gate in validated:
        child = create_run(
            session,
            parent.task,
            run_type="agent",
            capability="agent.media.prepare"
            if key == "create_media"
            else "agent.execute"
            if key == "report"
            else "agent.step",
            executor_type="agent"
            if key == "report"
            else "agent_media"
            if key == "create_media"
            else "browser"
            if key == "browser"
            else "github_read"
            if key == "github_read"
            else "agent_tool",
            execution_target="host" if key in {"browser", "github_read"} else "container",
            parameters={
                **(
                    {
                        "connector_id": str(definition.github.connector_id),
                        "repository": definition.github.repository,
                        "operation": "overview",
                    }
                    if key == "github_read" and definition.github
                    else {}
                ),
                "definition": parent.parameters["definition"],
                "endpoint": parent.parameters.get("endpoint"),
                "skill_snapshots": parent.parameters.get("skill_snapshots") or [],
                "tool": None if key == "report" else key,
                "gate": gate,
                "step_index": index,
                "deadline_at": deadline_at.isoformat(),
                **({"execution_deadline_at": deadline_at.isoformat()} if definition.media else {}),
                **(
                    {"media_inputs": parent.parameters.get("media_inputs", [])}
                    if key == "create_media"
                    else {}
                ),
            },
            permissions=[p for p in parent.effective_permissions if p in {"network_read", "github_read"}]
            if key == "github_read"
            else execution_permissions(parent, definition),
            retry_class="inspect",
            triggered_by=parent.triggered_by,
            agent_id=parent.agent_id,
            parent_run_id=parent.id,
        )
        if key == "github_read":
            github_target.status, github_target.last_run_id, github_target.updated_at = (
                "checking",
                child.id,
                utcnow(),
            )
        if previous is not None:
            depend_on(session, child, previous)
        if gate == "approval":
            from app.approvals import request_run_approval

            request_run_approval(
                session,
                child,
                action="agent.step" if key != "report" else "agent.execute",
                reason="This workflow step requires approval before it starts",
                payload={
                    "agent_id": parent.agent_id,
                    "parent_run_id": parent.id,
                    "step": key,
                    "step_index": index,
                },
            )
        elif key == "report" or key == "create_media" and definition.media.description_source == "goal":
            from app.llama import prepare_consumer

            prepare_consumer(session, child)
        created.append(child)
        previous = child
    plan = {
        "workflow_mode": definition.workflow_mode,
        "steps": [
            {
                "key": child.parameters.get("tool") or "report",
                "run_id": child.id,
                "gate": child.parameters.get("gate", "none"),
                "depends_on": created[index - 1].id if index else None,
            }
            for index, child in enumerate(created)
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
        json.dump(plan, handle)
        handle.flush()
        register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="workflow-steps.json",
            run_id=parent.id,
            metadata={"workflow": True, "mode": definition.workflow_mode},
        )
    append_event(session, parent.id, "workflow.published", plan)
    return created


class AgentToolExecutor:
    name = "agent_tool"

    def execute(self, session, run):
        from app.agent_executor import LocalAgentExecutor, execute_context_tool, persist_agent_memory

        session.refresh(run)
        if LocalAgentExecutor._canceled(session, run):
            return "done"
        definition = AgentSettings.model_validate(run.parameters["definition"])
        tool = run.parameters.get("tool")
        if tool not in CONTEXT_STEPS or tool not in definition.tools or not agent_tool(tool).operational:
            mark_failed(
                session, run, "InventedStep", f"Refusing an invented or unavailable agent step: {tool}"
            )
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={"tool": tool})
        transition(session, run, RunStatus.RUNNING, event_type="executor.started", payload={"tool": tool})
        session.commit()
        remember = "remember_workflow" in definition.tools and tool in WORKFLOW_MEMORY_TOOLS
        try:
            if run.agent_id is None:
                from app.conversation_data import reviewed_research_step

                reviewed_research_step(session, run)
            if remember:
                from app.permissions import require

                require(run.effective_permissions, "memory_write")
            deadline = _remaining_deadline(run, definition)
            result = execute_context_tool(session, run, definition, tool, deadline)
            if result is None:
                LocalAgentExecutor._canceled(session, run)
                return "done"
            session.refresh(run)
            if run.status in {"cancel_requested", "canceled"}:
                if run.status == "cancel_requested":
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
                return "done"
            if remember:
                append_event(session, run.id, "tool.requested", {"tool": "remember_workflow"})
            try:
                with session.begin_nested():
                    run.metadata_json = {**run.metadata_json, "observation": result, tool: result}
                    if remember:
                        persist_agent_memory(
                            session,
                            run,
                            result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                            tags=["agent-workflow", tool],
                            tool="remember_workflow",
                            excerpt_notice="\n\n[Excerpt: open the source Run for the full observation.]",
                        )
                    run.summary = f"{tool} completed."
                    transition(
                        session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={"tool": tool}
                    )
            except Exception:
                if remember:
                    append_event(
                        session,
                        run.id,
                        "tool.failed",
                        {"tool": "remember_workflow", "error": "Workflow observation could not be retained"},
                    )
                raise
            session.commit()
        except Exception as exc:
            session.refresh(run)
            if not LocalAgentExecutor._canceled(session, run):
                mark_failed(session, run, type(exc).__name__, str(exc) or "Agent step failed")
        return "done"


def _remaining_deadline(run, definition):
    raw = run.parameters.get("deadline_at")
    if raw:
        from datetime import datetime

        deadline_at = datetime.fromisoformat(raw)
        remaining = (deadline_at - utcnow()).total_seconds()
        if remaining <= 0:
            raise ValueError("Agent runtime limit exceeded before this step started")
        return time.monotonic() + remaining
    return time.monotonic() + definition.maximum_runtime
