"""Explicit completed-analysis references for the existing disabled Agent Factory."""

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.agent_schema import AgentSettings
from app.chat_policy import agent_draft_policy
from app.conversation_data_schema import DataScope
from app.models import Artifact, Message, Run

ERROR = "Choose a completed analysis in this conversation with available, unchanged sources."


class RepeatProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    trigger: Literal["manual", "cron", "interval", "datetime"] = "manual"
    cron_expr: str = Field(default="", max_length=120)
    interval_seconds: int | None = None
    run_at: datetime | None = None
    output_expectation: str = Field(default="A verified local data report.", max_length=4000)


def requested(content):
    from app.conversation_data_reference import instruction

    text = instruction(content)
    prefix = r"^(?:(?:please|now|then|proszę|prosze|teraz)\s+){0,3}"
    article = r"(?:(?:a|an|the|new|persistent|recurring|daily|mi|nowego|nowy|stałego|stalego|cyklicznego|codziennego)\s+){0,3}"
    reference = r"(?:\b(?:this|that|the previous|the last)\s+analysis\b|\b(?:t[ęeą]|tej|t[ąa]|poprzedni[ąa]|ostatni[ąa])\s+analiz\w*\b)"
    agent = re.search(
        prefix + r"(?:create|make|save|stw[oó]rz|utw[oó]rz|zapisz)\s+" + article + r"(?:agent|agenta)\b",
        text,
        re.I,
    )
    saved = re.search(
        prefix
        + r"(?:save|zapisz|zamie[ńn]|przekszta[łl][ćc])\s+"
        + reference
        + r"\s+(?:as|jako|w)\s+"
        + article
        + r"(?:agent|agenta)\b",
        text,
        re.I,
    )
    return bool((agent or saved) and re.search(reference, text, re.I))


def capture(session, conversation_id, user, root, *, for_execution=False):
    from app.conversation_data import definition, verify_document_sources, verify_source_files
    from app.conversation_data_reference import source_reference
    from app.data_agents import freeze_inputs

    if (
        root is None
        or user is None
        or root.conversation_id != conversation_id
        or user.conversation_id != conversation_id
    ):
        raise ValueError(ERROR)
    reference = source_reference(session, user, root)
    scope = DataScope.model_validate(root.parameters["data"])
    frozen = freeze_inputs(session, scope.files(), research=bool(scope.context_tools()))
    if scope.documents:
        from app.agent_documents import reviewed_scope

        reviewed_scope(session, scope.documents)
    if for_execution:
        verify_source_files(frozen)
        verify_document_sources(session, scope)
    result = session.scalar(
        select(Run).where(
            Run.task_id == root.task_id, Run.executor_type == "agent_data_result", Run.status == "succeeded"
        )
    )
    if result is None:
        raise ValueError(ERROR)
    result_data = result.metadata_json["data_result"]
    artifacts = []
    for key in ("report_artifact_id", "download_artifact_id"):
        item = session.get(Artifact, result_data[key], populate_existing=True)
        if item is None or item.trashed_at is not None:
            raise ValueError("The completed analysis lost a verified result artifact")
        from pathlib import Path

        from app.paths import artifact_relative

        expected_owner = result.parameters["python_run_id"] if key == "report_artifact_id" else result.id
        if (
            item.run_id != expected_owner
            or item.relative_path != artifact_relative(item.id, Path(item.relative_path).suffix)
            or key == "report_artifact_id"
            and (
                item.mime_type != "application/json" or item.metadata_json.get("output_name") != "result.json"
            )
            or key == "download_artifact_id"
            and (item.mime_type != "text/csv" or not item.metadata_json.get("agent_data_download"))
        ):
            raise ValueError("Result artifact changed its analysis ownership")
        if for_execution:
            from app.python_execution import read_owned_file

            raw = read_owned_file(item.relative_path, item.size_bytes, item.sha256, binary=True)
            if key == "report_artifact_id":
                from app.data_agents import DataAnswer

                if DataAnswer.model_validate_json(raw).model_dump() != {
                    k: result_data[k] for k in DataAnswer.model_fields
                }:
                    raise ValueError("The completed result differs from its verified report")
        artifacts.append(
            {
                "id": item.id,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "relative_path": item.relative_path,
            }
        )
    settings = definition(root).model_dump(mode="json")
    return {
        "source_run_id": root.id,
        "source_user_message_id": user.id,
        "result_run_id": result.id,
        "result_sha256": hashlib.sha256(json.dumps(result_data, sort_keys=True).encode()).hexdigest(),
        "result_artifacts": artifacts,
        "input_names": [session.get(Artifact, item["artifact_id"]).original_filename for item in frozen],
        "source_message_id": reference["message_id"],
        "reference": reference,
        "definition": settings,
        "data_inputs": frozen,
        "documents": [s.name for s in scope.documents.snapshots] if scope.documents else [],
        "live_public_sources": bool(scope.research),
    }


def resolve(session, conversation, body, mode):
    selected = getattr(body, "analysis_agent_source_run_id", None)
    if selected and (
        mode not in {"work", "orchestrator"} or body.action != "agent.create" or not requested(body.content)
    ):
        raise HTTPException(422, "Create an agent from the selected analysis with an explicit Work request")
    if (
        mode not in {"work", "orchestrator"}
        or body.action not in {"auto", "agent.create"}
        or not requested(body.content)
    ):
        return body, None
    if (
        any(
            getattr(body, key, None)
            for key in (
                "attachments",
                "data",
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
        raise HTTPException(422, "Repeat an analysis without adding other file, project or Web scopes")
    if len(body.content) > 16000:
        raise HTTPException(422, "Keep the agent-draft instruction within 16000 characters")
    from app.chat_providers import BUILTIN_KEY, get_provider
    from app.models import ChatWorkContext

    binding = session.get(ChatWorkContext, conversation.id)
    if binding is not None and binding.task_id:
        raise HTTPException(422, "Open General Work to create an agent from an analysis")
    if (
        conversation.provider != BUILTIN_KEY
        or get_provider(session, conversation.provider).location != "local"
    ):
        raise HTTPException(422, "Select Local AI to prepare a source-bound agent draft")
    query = (
        select(Message, Run)
        .outerjoin(Run, Message.run_id == Run.id)
        .where(Message.conversation_id == conversation.id, Message.role == "user")
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(64)
    )
    if selected:
        query = query.where(Run.id == str(selected))
    rows = session.execute(query)
    for user, root in rows:
        if user.metadata_json.get("data_scope") or root and root.parameters.get("data"):
            try:
                source = capture(session, conversation.id, user, root)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise HTTPException(422, ERROR) from exc
            return body.model_copy(
                update={
                    "action": "agent.create",
                    "project_defaults": None,
                    "web_search": body.web_search.model_copy(update={"enabled": False}),
                }
            ), source
    raise HTTPException(422, ERROR)


def verified(session, draft):
    """Recheck current request and exact completed source before inference/publication."""
    session.flush()
    session.expire_all()
    source = draft.parameters.get("data_agent_source")
    if not isinstance(source, dict):
        raise ValueError("Agent draft lost its completed-analysis source")
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
        or not agent_draft_policy(parent.parameters)
        or parent.parameters.get("action") != "agent.create"
        or parent.parameters.get("data_agent_source") != source
        or current is None
        or current.role != "user"
        or current.run_id != parent.id
        or current.conversation_id != draft.conversation_id
        or current.metadata_json.get("data_agent_source") != source
        or current.metadata_json.get("user_text", current.content).strip()
        != parent.parameters["content"].strip()
        or not requested(parent.parameters["content"])
    ):
        raise ValueError("Agent draft changed its originating analysis request")
    root = session.get(Run, source.get("source_run_id"))
    user = session.get(Message, source.get("source_user_message_id"))
    if capture(session, draft.conversation_id, user, root, for_execution=True) != source:
        raise ValueError("Completed analysis or its selected sources changed before agent creation")
    return source


def repeat_definition(source, proposal, timezone):
    base = source["definition"]
    return AgentSettings.model_validate(
        {
            **base,
            **proposal.model_dump(mode="json"),
            "schedule_timezone": timezone,
            "enabled": False,
            "project_id": None,
            "permission_profile": "agent_local",
        }
    )
