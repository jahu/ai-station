"""Current selected inputs prepare a disabled agent through the existing factory."""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from app.agent_schema import AgentSettings
from app.chat_policy import agent_draft_policy, agent_draft_requested
from app.conversation_data_schema import DataScope
from app.data_agent_draft import RepeatProposal
from app.models import Artifact, ChatWorkContext, Message, Run
from app.permissions import require


class SelectedProposal(RepeatProposal):
    output_expectation: str = Field(
        default="An inspectable result matching the reviewed task.", max_length=4000
    )
    family: Literal["data", "report", "code"] = "data"
    goal: str = Field(min_length=1, max_length=16000)
    system_prompt: str = Field(default="", max_length=8000)


def requested(content):
    from app.conversation_data_reference import instruction

    return agent_draft_requested({"content": instruction(content)})


def freeze(session, raw, instruction, *, for_execution=False):
    from app.agent_documents import reviewed_scope
    from app.conversation_data import verify_document_sources, verify_source_files
    from app.data_agents import freeze_inputs

    scope = DataScope.model_validate(raw.model_dump(mode="json") if isinstance(raw, DataScope) else raw)
    if scope.documents:
        reviewed_scope(session, scope.documents, freeze=not for_execution)
    inputs = freeze_inputs(session, scope.files(), research=bool(scope.context_tools()))
    if for_execution:
        verify_source_files(inputs)
        verify_document_sources(session, scope)
    settings = AgentSettings(
        name="Selected data agent",
        goal=instruction,
        tools=["python_data", *scope.context_tools()],
        model=scope.model,
        data=scope.files(),
        documents=scope.documents,
        search_query=scope.research.search_query if scope.research else "",
        fetch_urls=scope.research.fetch_urls if scope.research else [],
        maximum_runtime=scope.maximum_runtime,
        enabled=False,
    )
    ids = [item["artifact_id"] for item in inputs] + (
        [str(aid) for aid in scope.documents.artifact_ids] if scope.documents else []
    )
    return {
        "kind": "selected_inputs",
        "scope": scope.model_dump(mode="json"),
        "definition": settings.model_dump(mode="json"),
        "data_inputs": inputs,
        "artifact_ids": list(dict.fromkeys(ids)),
        "input_names": [session.get(Artifact, item["artifact_id"]).original_filename for item in inputs],
        "documents": [s.name for s in scope.documents.snapshots] if scope.documents else [],
        "live_public_sources": bool(scope.research),
    }


def prepare(session, conversation, body, mode):
    if body.data is None or not (body.action == "agent.create" or requested(body.content)):
        return body, None
    if mode not in {"work", "orchestrator"}:
        raise HTTPException(422, "Agent creation is not authorized for this explicit legacy request")
    from app.chat_providers import BUILTIN_KEY, get_provider
    from app.data_agent_draft import requested as repeated_analysis

    binding = session.get(ChatWorkContext, conversation.id)
    if binding is not None and binding.task_id:
        raise HTTPException(422, "Leave the selected project task before creating an agent with these inputs")
    if (
        conversation.provider != BUILTIN_KEY
        or get_provider(session, conversation.provider).location != "local"
    ):
        raise HTTPException(422, "Select Local AI to prepare an agent with selected inputs")
    if (
        body.action not in {"auto", "data.analyze", "agent.create"}
        or body.action != "agent.create"
        and not requested(body.content)
        or repeated_analysis(body.content)
        or body.analysis_agent_source_run_id
        or any(
            getattr(body, key, None)
            for key in (
                "attachments",
                "image_artifact_ids",
                "audio_artifact_id",
                "speech_text",
                "music",
                "media",
                "github",
                "coding",
                "new_project",
                "continuation",
                "commit",
                "publish",
                "load",
                "stop",
                "upscale_result",
            )
        )
        or body.web_search.query.strip()
        or body.web_search.render_pages
    ):
        raise HTTPException(422, "Create an agent using only these selected data inputs and reviewed sources")
    if len(body.content) > 16000:
        raise HTTPException(422, "Keep the agent instruction within 16000 characters")
    try:
        source = freeze(session, body.data, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return body.model_copy(
        update={
            "data": None,
            "action": "agent.create",
            "project_defaults": None,
            "reasoning": None,
            "web_search": body.web_search.model_copy(update={"enabled": False}),
        }
    ), source


def verified(session, draft):
    session.flush()
    session.expire_all()
    require(draft.effective_permissions, "manage_agents")
    source = draft.parameters.get("selected_data_agent")
    if not isinstance(source, dict):
        raise ValueError("Selected-input agent draft lost its source scope")
    if source.get("artifact_ids"):
        require(draft.effective_permissions, "filesystem_read")
    parent = session.get(Run, draft.parent_run_id)
    current = session.get(Message, parent.parameters.get("user_message_id")) if parent else None
    if (
        parent is None
        or parent.executor_type != "orchestrator"
        or parent.status != "succeeded"
        or parent.task_id != draft.task_id
        or parent.task.conversation_id != draft.conversation_id
        or parent.task.agent_id is not None
        or parent.agent_id is not None
        or draft.agent_id is not None
        or draft.parameters.get("instruction", "").strip() != parent.parameters["content"].strip()
        or draft.parameters.get("model") != parent.parameters.get("model")
        or parent.conversation_id != draft.conversation_id
        or not agent_draft_policy(parent.parameters)
        or parent.parameters.get("action") != "agent.create"
        or parent.parameters.get("selected_data_agent") != source
        or current is None
        or current.role != "user"
        or current.run_id != parent.id
        or current.conversation_id != draft.conversation_id
        or current.metadata_json.get("selected_data_agent") != source
        or current.metadata_json.get("user_text", current.content).strip()
        != parent.parameters["content"].strip()
        or source.get("source_run_id") != parent.id
        or source.get("source_user_message_id") != current.id
    ):
        raise ValueError("Selected-input draft changed its current conversation request")
    require(parent.effective_permissions, "manage_agents")
    if source.get("artifact_ids"):
        require(parent.effective_permissions, "filesystem_read")
    frozen = freeze(session, source["scope"], parent.parameters["content"], for_execution=True)
    if {**frozen, "source_run_id": parent.id, "source_user_message_id": current.id} != source:
        raise ValueError("Selected inputs or their reviewed scope changed before agent creation")
    return source


def allowed_families(source):
    scope = DataScope.model_validate(source["scope"])
    if scope.input_artifact_ids or scope.operation == "create":
        return ["data"]
    return ["data", "report", "code"] if scope.context_tools() else ["data"]


def prepared_family(settings):
    return (
        "data"
        if "python_data" in settings.tools
        else "code"
        if "coding_local" in settings.tools
        else "report"
    )


def definition(source, proposal, timezone, *, report_model=None):
    if proposal.family not in allowed_families(source):
        raise ValueError(
            "Choose a family supported by the selected inputs; data files and file creation require data"
        )
    base = source["definition"]
    values = {
        **base,
        **proposal.model_dump(mode="json", exclude={"family"}),
        "schedule_timezone": timezone,
        "enabled": False,
        "project_id": None,
        "permission_profile": "agent_local",
    }
    if proposal.family != "data":
        scope = DataScope.model_validate(source["scope"])
        values.update(data=None, tools=scope.context_tools())
        if proposal.family == "code":
            values.update(
                tools=["coding_local", *scope.context_tools()],
                workspace_policy={"auto_install_dependencies": True, "auto_validate": True},
            )
        else:
            values["model"] = base["model"] if base["model"] != "auto" else report_model
            if not values["model"] or values["model"] == "auto":
                raise ValueError("Choose a local conversation model for the report agent")
    return AgentSettings.model_validate(values)
