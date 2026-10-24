"""Explicit current-user controls reuse ordinary agent lifecycle operations."""

import re

from fastapi import HTTPException
from sqlalchemy import select, update

from app.agent_email_schema import digest
from app.agent_schema import AgentSettings
from app.db import utcnow
from app.events import append_event
from app.models import Agent, ChatWorkContext, Message, Run, RunEvent, Task
from app.permissions import PermissionDenied, require
from app.runs import create_run, create_task, run_dict, transition
from app.serialize import iso
from app.state import TERMINAL, RunStatus
from app.task_control import cancel_task, lock_task


def operation(text):
    text = " ".join(text.strip().lower().split()).rstrip(".! ")
    text = re.sub(r"^(?:(?:please|proszę|prosze|teraz)\s+){0,2}", "", text)
    target = r"(?:this|the|that|last) agent"
    polish = r"(?:tego|ostatniego|tego ostatniego) agenta"
    if re.fullmatch(rf"(?:run|start) {target}(?: now)?|uruchom {polish}(?: teraz)?", text):
        return "run"
    if re.fullmatch(
        rf"pause {target}(?:'s schedule)?|pause (?:the |this )?agent schedule|"
        rf"wstrzymaj {polish}|(?:wstrzymaj|wyłącz|wylacz) harmonogram(?: {polish})?",
        text,
    ):
        return "pause"
    if re.fullmatch(
        rf"stop {target}(?:'s current (?:run|task))?|stop (?:the |this )?agent's current (?:run|task)|"
        rf"zatrzymaj (?:bieżące|biezace|aktualne) (?:zadanie|wykonanie)(?: {polish})?|"
        rf"zatrzymaj {polish}",
        text,
    ):
        return "stop"
    return None


def creation_source(session, conversation_id):
    messages = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.role == "assistant")
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(200)
    )
    for message in messages:
        meta = message.metadata_json
        if (
            meta.get("superseded")
            or meta.get("partial")
            or meta.get("agent_control")
            or not meta.get("agent_id")
        ):
            continue
        origin = session.get(Run, message.run_id) if message.run_id else None
        if not (
            origin
            and origin.status == "succeeded"
            and origin.executor_type == "orchestrator"
            and origin.conversation_id == conversation_id
            and origin.task.conversation_id == conversation_id
            and origin.metadata_json.get("plan", {}).get("action") == "agent.create"
        ):
            raise ValueError("The latest agent reference has no intact creation result; open its workspace")
        require(origin.effective_permissions, "manage_agents")
        draft = session.get(Run, meta.get("draft_run_id", ""))
        if draft:
            valid = (
                draft.executor_type == "agent_draft"
                and draft.status == "succeeded"
                and draft.parent_run_id == origin.id
                and draft.task_id == origin.task_id
                and draft.conversation_id == conversation_id
                and draft.metadata_json.get("agent_id") == meta["agent_id"]
            )
        else:
            valid = not meta.get("draft_run_id") and bool(
                session.scalar(
                    select(RunEvent.id)
                    .where(
                        RunEvent.run_id == origin.id,
                        RunEvent.event_type == "agent.draft.created",
                        RunEvent.payload["agent_id"].as_string() == meta["agent_id"],
                    )
                    .limit(1)
                )
            )
        agent = session.get(Agent, meta["agent_id"])
        if not valid or agent is None:
            raise ValueError("The latest agent is unavailable or its source changed; open its workspace")
        return message, origin, agent
    raise ValueError("Create an agent in this conversation first, or run an existing agent from Agents")


def prepare(session, conversation, body, mode):
    op = operation(body.content) if body.action == "auto" else None
    if op is None:
        return body, None
    if mode not in {"work", "orchestrator"}:
        raise HTTPException(422, "Switch to Work to control an agent")
    binding = session.get(ChatWorkContext, conversation.id)
    mixed = any(
        getattr(body, field, None)
        for field in (
            "attachments",
            "image_artifact_ids",
            "audio_artifact_id",
            "continuation",
            "media",
            "music",
            "data",
            "github",
            "coding",
            "new_project",
            "project_defaults",
            "commit",
            "publish",
            "load",
            "stop",
            "upscale_result",
            "speech_text",
            "analysis_agent_source_run_id",
        )
    )
    if (
        mixed
        or binding
        and binding.task_id
        or (body.web_search.query.strip() or body.web_search.render_pages)
    ):
        raise HTTPException(422, "Send the agent control separately, in General Work without attachments")
    try:
        source, origin, agent = creation_source(session, conversation.id)
    except (ValueError, PermissionDenied) as exc:
        raise HTTPException(409, str(exc)) from exc
    from app.schedule import active_run

    active_id = active_run(session, agent.id) if op == "stop" else None
    active = session.get(Run, active_id) if active_id else None
    scope = {
        "operation": op,
        "agent_id": agent.id,
        "expected_updated_at": iso(agent.updated_at),
        "definition_hash": definition_hash(agent),
        "source_message_id": source.id,
        "source_run_id": origin.id,
        "target_task_id": active.task_id if active else None,
    }
    from app.web_search import SearchOptions

    return body.model_copy(update={"web_search": SearchOptions(enabled=False), "reasoning": None}), scope


def definition_hash(agent):
    # Raw persisted values also cover an unavailable old definition: Pause must
    # not need a model/runtime or schema repair merely to remove authority.
    values = {key: getattr(agent, key) for key in AgentSettings.model_fields}
    return digest(
        {key: iso(value) if hasattr(value, "isoformat") else value for key, value in values.items()}
    )


def enqueue(session, conversation, user, body, scope):
    task = create_task(
        session,
        title=body.content,
        prompt=body.content,
        capability="agent.control",
        intent="agent.control",
        conversation_id=conversation.id,
    )
    run = create_run(
        session,
        task,
        run_type="control",
        capability="agent.control",
        executor_type="agent_control",
        execution_target="container",
        permissions=["manage_agents"],
        retry_class="inspect",
        parameters={"content": body.content, "user_message_id": user.id, "scope": scope},
    )
    user.run_id = run.id
    user.metadata_json = {**user.metadata_json, "agent_control": scope}
    session.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content="",
            run_id=run.id,
            metadata_json={"agent_control": scope},
        )
    )
    conversation.updated_at = utcnow()
    return run_dict(run)


def verified(session, run):
    require(run.effective_permissions, "manage_agents")
    scope = run.parameters["scope"]
    user = session.get(Message, run.parameters["user_message_id"])
    if not (
        run.task.conversation_id == run.conversation_id
        and run.task.intent == "agent.control"
        and user
        and user.role == "user"
        and user.conversation_id == run.conversation_id
        and user.run_id == run.id
        and user.content == run.parameters["content"]
        and run.task.prompt == user.content
        and user.metadata_json.get("agent_control") == scope
        and user.metadata_json.get("execution_mode") in {"work", "orchestrator"}
        and operation(user.content) == scope["operation"]
    ):
        raise ValueError("The originating control request changed; send it again")
    source, origin, agent = creation_source(session, run.conversation_id)
    if (source.id, origin.id, agent.id) != (
        scope["source_message_id"],
        scope["source_run_id"],
        scope["agent_id"],
    ):
        raise ValueError("The referenced agent changed; inspect it and send again")
    session.execute(update(Agent).where(Agent.id == agent.id).values(updated_at=Agent.updated_at))
    session.refresh(agent)
    if (
        iso(agent.updated_at) != scope["expected_updated_at"]
        or definition_hash(agent) != scope["definition_hash"]
    ):
        raise ValueError("The agent definition changed after Send; inspect it and send again")
    return agent, scope


def linked_run(session, message, run):
    if (
        not run
        or run.executor_type != "agent_control"
        or run.status != "succeeded"
        or run.conversation_id != message.conversation_id
        or run.task.conversation_id != message.conversation_id
    ):
        return None
    result = run.metadata_json.get("agent_control_result")
    if (
        not isinstance(result, dict)
        or message.role != "assistant"
        or message.metadata_json.get("agent_control_result") != result
    ):
        return None
    target = session.get(Run, result.get("workflow_run_id", ""))
    if not target or target.executor_type != "agent_workflow" or target.agent_id != result.get("agent_id"):
        return None
    # Run actions publish a two-way controller link. Stop/busy may refer to an
    # existing ordinary execution, checked against the frozen same-agent Task.
    if (
        result.get("outcome") == "queued"
        and target.metadata_json.get("conversation_control_run_id") != run.id
    ):
        return None
    if target.task_id != result.get("task_id"):
        return None
    active = list(
        session.scalars(
            select(Run.status).where(Run.task_id == target.task_id, Run.status.not_in(TERMINAL)).limit(1025)
        )
    )
    status = "cancel_requested" if "cancel_requested" in active else (active[0] if active else target.status)
    return {"id": target.id, "status": status, "agent_id": target.agent_id, "task_id": target.task_id}


class AgentControlExecutor:
    name = "agent_control"

    def execute(self, session, run):
        lock_task(session, run.task)
        session.refresh(run)
        if run.status == "cancel_requested" or run.task.metadata_json.get("stop_requested_at"):
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        agent, scope = verified(session, run)
        message = session.scalar(select(Message).where(Message.run_id == run.id, Message.role == "assistant"))
        if message is None or message.metadata_json.get("agent_control") != scope:
            raise ValueError("The control response changed; send again")
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        from app.schedule import active_run, launch_agent

        op = scope["operation"]
        result = {"operation": op, "agent_id": agent.id}
        if op == "pause":
            from app.agent_lifecycle import pause_agent

            pause_agent(session, agent)
            result["outcome"] = "paused"
            text = "Future executions are paused. Current work, if any, continues; use ‘Stop this agent’ to stop it."
        elif op == "run":
            active_id = active_run(session, agent.id)
            active = session.get(Run, active_id) if active_id else None
            if active:
                root = session.scalar(
                    select(Run).where(Run.task_id == active.task_id, Run.executor_type == "agent_workflow")
                )
                result.update(
                    outcome="already_running",
                    workflow_run_id=root.id if root else active.id,
                    task_id=active.task_id,
                )
                text = "This agent already has an active execution. No additional work was queued."
            elif not agent.enabled:
                result["outcome"] = "needs_review"
                text = "This agent is paused or not yet enabled. Review and enable its definition before running it."
            else:
                # launch_agent may fail after flushing partial work; a savepoint
                # prevents any partial graph from escaping a rejected operation.
                with session.begin_nested():
                    root_id = launch_agent(session, agent, triggered_by="user")
                    root = session.get(Run, root_id)
                    root.metadata_json = {**root.metadata_json, "conversation_control_run_id": run.id}
                    root.task.metadata_json = {
                        **root.task.metadata_json,
                        "conversation_control_run_id": run.id,
                        "originating_conversation_id": run.conversation_id,
                    }
                result.update(outcome="queued", workflow_run_id=root.id, task_id=root.task_id)
                text = "Agent execution queued. You can keep using this conversation while it works."
        else:
            target = session.get(Task, scope["target_task_id"]) if scope["target_task_id"] else None
            if target and target.agent_id != agent.id:
                raise ValueError("The current execution no longer belongs to this agent")
            active = (
                session.scalar(select(Run.id).where(Run.task_id == target.id, Run.status.not_in(TERMINAL)))
                if target
                else None
            )
            if active:
                cancel_task(session, target)
                root = session.scalar(
                    select(Run).where(Run.task_id == target.id, Run.executor_type == "agent_workflow")
                )
                result.update(
                    outcome="stop_requested", task_id=target.id, workflow_run_id=root.id if root else active
                )
                text = "Stop requested for the execution selected when you sent this message. Future scheduling is unchanged."
            else:
                result["outcome"] = "already_finished"
                text = "That execution is no longer active. No newer execution was stopped; future scheduling is unchanged."
        run.metadata_json = {**run.metadata_json, "agent_control_result": result}
        message.metadata_json = {
            **message.metadata_json,
            "agent_id": agent.id,
            "agent_control_result": result,
        }
        message.content = text
        run.summary = text
        append_event(session, run.id, f"agent.control.{op}", result)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        # The worker commits control result and the normal agent graph together.
        return "done"
