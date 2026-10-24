"""Current selected inputs prepare a disabled agent through the existing factory."""

import re

from fastapi import HTTPException
from pydantic import Field

from app.agent_schema import AgentSettings
from app.conversation_data_schema import DataScope
from app.data_agent_draft import RepeatProposal
from app.models import Artifact, ChatWorkContext, Message, Run
from app.permissions import require


class SelectedProposal(RepeatProposal):
    goal: str = Field(min_length=1, max_length=16000)
    system_prompt: str = Field(default="", max_length=8000)


def requested(content):
    from app.conversation_data_reference import instruction

    return bool(
        re.search(
            r"^(?:(?:please|now|then|proszę|prosze|teraz)\s+){0,3}"
            r"(?:create|make|save|stw[oó]rz|utw[oó]rz|zapisz)\s+"
            r"(?:(?:a|an|the|new|persistent|recurring|daily|mi|nowego|nowy|stałego|stalego|cyklicznego|codziennego)\s+){0,3}"
            r"(?:agent|agenta)\b",
            instruction(content),
            re.I,
        )
    )


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
        raise HTTPException(422, "Switch to Work to create an agent with these selected inputs")
    from app.chat_providers import BUILTIN_KEY, get_provider
    from app.data_agent_draft import requested as repeated_analysis

    binding = session.get(ChatWorkContext, conversation.id)
    if binding is not None and binding.task_id:
        raise HTTPException(422, "Choose General Work to create an agent with selected inputs")
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
        or parent.conversation_id != draft.conversation_id
        or parent.parameters.get("policy_mode") != "work"
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


def definition(source, proposal, timezone):
    return AgentSettings.model_validate(
        {
            **source["definition"],
            **proposal.model_dump(mode="json"),
            "schedule_timezone": timezone,
            "enabled": False,
            "project_id": None,
            "permission_profile": "agent_local",
        }
    )
