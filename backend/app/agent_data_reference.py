"""Bind an explicit new data operation to an agent's verified historical input scope."""

from sqlalchemy import select

from app.agent_email_results import verified_result
from app.agent_schema import AgentSettings
from app.conversation_agent_control import creation_source, definition_hash, linked_run, operation
from app.conversation_data_schema import DataScope
from app.data_agents import created_input_ids, freeze_inputs
from app.data_research import execution_inputs, verify_research
from app.models import Message, Run
from app.permissions import require


def source_reference(session, user, control, *, use_result_file=False):
    from app.conversation_data_reference import quoted_context

    if control is None or control.executor_type != "agent_control":
        return None
    scope = control.parameters.get("scope") or {}
    if not isinstance(scope, dict):
        raise ValueError("The originating agent scope changed")
    if scope.get("operation") != "run":
        if (user.metadata_json.get("agent_control") or {}).get("operation") == "run":
            raise ValueError("The originating agent scope is missing")
        return None
    require(control.effective_permissions, "manage_agents")
    if (
        user.role != "user"
        or user.id != control.parameters.get("user_message_id")
        or user.run_id != control.id
        or user.conversation_id != control.conversation_id
        or control.task.conversation_id != control.conversation_id
        or user.content != control.parameters.get("content")
        or control.task.prompt != user.content
        or operation(user.content) != "run"
        or user.metadata_json.get("agent_control") != scope
    ):
        raise ValueError("The originating agent action changed")
    _, origin, agent = creation_source(
        session, control.conversation_id, message_id=scope["source_message_id"], creation_only=True
    )
    if origin.id != scope.get("source_run_id") or agent.id != scope.get("agent_id"):
        raise ValueError("The agent source is not its verified conversation creation")
    replies = list(
        session.scalars(
            select(Message)
            .where(
                Message.run_id == control.id,
                Message.role == "assistant",
                Message.conversation_id == user.conversation_id,
            )
            .limit(2)
        )
    )
    if len(replies) != 1 or any(
        replies[0].metadata_json.get(k) for k in ("partial", "superseded", "routing_only")
    ):
        raise ValueError("Choose a visible completed agent result")
    message = replies[0]
    linked = linked_run(session, message, control)
    if linked is None:
        if definition_hash(agent) != scope.get("definition_hash"):
            raise ValueError("The latest agent result is unavailable")
        if "python_data" not in agent.tools:
            return None
        raise ValueError("The latest data agent has no completed execution")
    root = session.get(Run, linked["id"])
    if "python_data" not in root.parameters.get("definition", {}).get("tools", []):
        return None
    if linked["status"] != "succeeded" or root.task.agent_id != root.agent_id:
        raise ValueError("The latest data execution is unfinished or failed")
    result = control.metadata_json["agent_control_result"]
    if result.get("outcome") == "queued" and (
        root.task.metadata_json.get("conversation_control_run_id") != control.id
        or root.task.metadata_json.get("originating_conversation_id") != user.conversation_id
    ):
        raise ValueError("The background execution lost its conversation owner")
    source = session.get(Run, linked.get("result_run_id", ""))
    if source is None or source.executor_type != "agent_data_result":
        raise ValueError("Choose one final data result")
    state = source.parameters.get("agent_data") or {}
    workflow = session.get(Run, state.get("workflow_run_id", ""))
    if (
        workflow is None
        or workflow.executor_type != "agent_workflow"
        or workflow.status != "succeeded"
        or workflow.parameters.get("definition") != state.get("definition")
        or workflow.parameters.get("data_inputs") != state.get("data_inputs")
        or source.project_id != workflow.project_id
    ):
        raise ValueError("The final data scope lost its workflow")
    current, visited = source, set()
    while current is not None and current.id != root.id and len(visited) < 100:
        if current.id in visited or current.task_id != root.task_id or current.agent_id != root.agent_id:
            raise ValueError("The data result has a different execution owner")
        visited.add(current.id)
        current = session.get(Run, current.parent_run_id) if current.parent_run_id else None
    if (
        current is None
        or current.id != root.id
        or workflow.task_id != root.task_id
        or workflow.agent_id != root.agent_id
    ):
        raise ValueError("The data result is outside this agent execution")
    if workflow.id != root.id and workflow.id not in visited:
        raise ValueError("The data workflow is not an ancestor of this result")
    definition = AgentSettings.model_validate(state["definition"])
    if definition.data is None:
        raise ValueError("The completed workflow has no data scope")
    python = session.get(Run, source.parameters.get("python_run_id", ""))
    if (
        python is None
        or python.parameters.get("agent_data") != state
        or python.project_id != workflow.project_id
        or not python.metadata_json.get("process_confirmed_gone")
        or python.metadata_json.get("data_result_run_id") != source.id
    ):
        raise ValueError("The completed Python result is not confirmed")
    saved = verified_result(session, source, root, definition)
    if not use_result_file:
        verify_research(session, workflow, state.get("data_research"), definition, for_execution=False)
        original = freeze_inputs(
            session, definition.data.model_dump(mode="json"), research=bool(state.get("data_research"))
        )
        if original != state.get("data_inputs"):
            raise ValueError("The original inputs changed after execution")
    executed = execution_inputs(state)
    if source.metadata_json["data_result"].get("input_artifact_ids") != [
        item["artifact_id"] for item in executed
    ]:
        raise ValueError("The report belongs to different original inputs")
    created = definition.data.operation == "create"
    if use_result_file:
        from app.data_agents import result_input_ids

        ids = result_input_ids(session, source)
    else:
        ids = created_input_ids(session, source) if created else [item["artifact_id"] for item in executed]
    derived = DataScope(
        input_artifact_ids=ids,
        max_repairs=definition.data.max_repairs,
        model=definition.model or "auto",
        maximum_runtime=min(definition.maximum_runtime, 600),
    )
    frozen = freeze_inputs(session, derived.files())
    from app.conversation_data import verify_source_files

    verify_source_files(frozen)
    if (
        not created
        and not use_result_file
        and [
            {k: v for k, v in item.items() if k not in {"preview_run_id", "preview_artifact_id"}}
            for item in frozen
        ]
        != executed
    ):
        raise ValueError("The selected input snapshots changed")
    from app.models import Artifact

    artifacts = [session.get(Artifact, aid) for aid in ids]
    captured = [
        {"artifact_id": a.id, "captured_at": a.created_at.isoformat()}
        for a in artifacts
        if a.metadata_json.get("agent_data_research") is True
    ]
    document_count = len(definition.documents.artifact_ids) if definition.documents and not created else 0
    return {
        "source_kind": "agent_data_inputs",
        **({"use_result_file": True, "result_run_id": source.id} if use_result_file else {}),
        "control_run_id": control.id,
        "workflow_run_id": root.id,
        "run_id": source.id,
        "message_id": message.id,
        "user_message_id": user.id,
        "artifact_id": ids[0],
        "artifact_ids": ids,
        "filenames": [a.original_filename for a in artifacts],
        "source_file_count": max(len(ids), len(definition.data.input_artifact_ids) + document_count)
        if not created and not use_result_file
        else len(ids),
        "data_scope": derived.model_dump(mode="json"),
        "data_inputs": frozen,
        "context": quoted_context(definition.goal, saved["report"]),
        **({"captured_sources": captured} if captured else {}),
        **({"created_from_instructions": True} if created else {}),
    }
