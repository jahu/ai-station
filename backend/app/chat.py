"""Conversation intent, immutable run context, and inspectable message history."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.assistant import (
    AssistantInputs,
    assistant_needs_provider,
    enqueue_assistant,
    explicit_plan,
    task_results,
)
from app.chat_attachments import TextAttachment, link_attachments, message_content, save_attachments
from app.chat_policy import POLICY_VERSION, policy_mode, validate_chat_scope
from app.chat_providers import BUILTIN_KEY, chat_permissions, snapshot_provider
from app.chat_reasoning import ReasoningOptions
from app.conversation_summary import (
    enqueue_summary,
    latest_summary,
    summary_memory,
    summary_view,
    uncovered_since,
    uncovered_text,
)
from app.db import session_scope, utcnow
from app.models import (
    ChatTurnRequest,
    ChatWorkContext,
    Conversation,
    MemoryEntry,
    Message,
    ModelFile,
    Run,
    Setting,
    Task,
)
from app.runs import create_run, create_task, run_dict
from app.serialize import conversation_dict, iso, message_dict
from app.state import TERMINAL

router = APIRouter(prefix="/api/chat")
DB = Annotated[Session, Depends(session_scope)]


class ConversationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    execution_mode: Literal["local", "orchestrator", "chat", "work"] = "local"
    title: str = Field(default="New conversation", min_length=1, max_length=300)
    provider: str = Field(default=BUILTIN_KEY, min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(default="", max_length=8000)
    temperature: float = Field(default=0.7, ge=0, le=2, allow_inf_nan=False)
    max_tokens: int = Field(default=2048, ge=1, le=8192)


class MessageBody(AssistantInputs):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=32000)
    attachments: list[TextAttachment] = Field(default_factory=list, max_length=4)
    execution_mode: Literal["auto", "local", "orchestrator", "chat", "work"] = "auto"
    reasoning: ReasoningOptions | None = None
    analysis_agent_source_run_id: UUID | None = None

    @model_validator(mode="after")
    def validate_context(self):
        if self.action == "system.inspect" and self.attachments:
            raise ValueError("Workstation inspection does not use attachments")
        message_content(self.content, self.attachments)
        return self


def turn_execution_mode(conversation, body) -> str:
    return conversation.execution_mode if body.execution_mode == "auto" else body.execution_mode


def conversation(session, conversation_id):
    row = session.get(Conversation, str(conversation_id))
    if row is None:
        raise HTTPException(404, "Conversation not found")
    return row


def conversation_view(session, row):
    from app.models import ChatProvider

    label = row.model
    if row.model.startswith("llamacpp:"):
        from pathlib import PurePosixPath

        model = session.get(ModelFile, row.model.removeprefix("llamacpp:"))
        if model:
            label = f"{PurePosixPath(model.host_path).parent.name} · {model.filename}"
    from app.chat_providers import normalize_provider_key

    provider = session.scalar(
        select(ChatProvider).where(ChatProvider.key == normalize_provider_key(row.provider))
    )
    return {
        **conversation_dict(row),
        "model_label": label,
        "settings_version": row.settings_version,
        "provider_name": provider.name if provider else row.provider,
        "provider_location": provider.location if provider else "local",
    }


def ensure_idle(session, conversation_id, *, allow_archived=False):
    row = conversation(session, conversation_id)
    if row.archived_at is not None and not allow_archived:
        raise HTTPException(409, "Restore this archived conversation before continuing")
    active = session.scalar(
        select(Run).where(Run.conversation_id == conversation_id, Run.status.not_in(TERMINAL))
    )
    if active is not None:
        raise HTTPException(409, "This conversation already has an active run")


@router.get("/conversations")
def conversations(
    session: DB,
    q: Annotated[str, Query(max_length=200)] = "",
    before: AwareDatetime | None = None,
    before_id: UUID | None = None,
    archived: bool = False,
):
    from app.chat_providers import ensure_builtin

    ensure_builtin(session)
    session.commit()
    if (before is None) != (before_id is None):
        raise HTTPException(422, "History cursor requires both timestamp and conversation ID")
    query = select(Conversation).where(
        Conversation.archived_at.is_not(None) if archived else Conversation.archived_at.is_(None)
    )
    if q.strip():
        text = q.strip()
        matching_message = (
            select(Message.id)
            .where(
                Message.conversation_id == Conversation.id,
                Message.content.contains(text, autoescape=True),
            )
            .exists()
        )
        query = query.where(or_(Conversation.title.contains(text, autoescape=True), matching_message))
    if before is not None:
        query = query.where(
            or_(
                Conversation.updated_at < before,
                and_(Conversation.updated_at == before, Conversation.id < str(before_id)),
            )
        )
    return [
        conversation_view(session, row)
        for row in session.scalars(
            query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(100)
        )
    ]


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationBody, session: DB):
    snapshot_provider(session, Conversation(provider=body.provider, model=body.model))
    row = Conversation(**body.model_dump())
    session.add(row)
    session.commit()
    return conversation_view(session, row)


@router.patch("/conversations/{conversation_id}")
def edit_conversation(conversation_id: UUID, body: ConversationBody, session: DB):
    row = conversation(session, conversation_id)
    ensure_idle(session, row.id)
    snapshot_provider(session, Conversation(provider=body.provider, model=body.model))
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    row.settings_version += 1
    session.commit()
    return conversation_view(session, row)


class ArchiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archived: StrictBool
    expected_settings_version: int = Field(ge=1)


@router.put("/conversations/{conversation_id}/archive")
def archive_conversation(conversation_id: UUID, body: ArchiveBody, session: DB):
    row = conversation(session, conversation_id)
    ensure_idle(session, row.id, allow_archived=True)
    now = utcnow()
    result = session.execute(
        update(Conversation)
        .where(Conversation.id == row.id, Conversation.settings_version == body.expected_settings_version)
        .values(
            archived_at=now if body.archived else None,
            updated_at=now,
            settings_version=Conversation.settings_version + 1,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Conversation settings changed; reload before archiving or restoring")
    session.commit()
    session.refresh(row)
    return conversation_view(session, row)


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_summary: StrictBool


@router.patch("/conversations/{conversation_id}/context")
def edit_context(conversation_id: UUID, body: ContextPolicy, session: DB):
    row = conversation(session, conversation_id)
    ensure_idle(session, row.id)
    row.auto_summary = body.auto_summary
    row.updated_at = utcnow()
    session.commit()
    return conversation_view(session, row)


@router.get("/conversations/{conversation_id}")
def detail(conversation_id: UUID, session: DB):
    row = conversation(session, conversation_id)
    # Bounded UI history; older messages remain in the database.
    messages = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == row.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(200)
        )
    )
    active = session.scalar(select(Run).where(Run.conversation_id == row.id, Run.status.not_in(TERMINAL)))
    runs = {
        r.id: r
        for r in session.scalars(select(Run).where(Run.id.in_([m.run_id for m in messages if m.run_id])))
    }
    summary_run = session.scalar(
        select(Run)
        .where(Run.conversation_id == row.id, Run.executor_type == "chat_summary")
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(1)
    )
    from app.conversation_agent_control import linked_run
    from app.work_context import project_context

    return {
        **conversation_view(session, row),
        "summary_update": {
            "id": summary_run.id,
            "status": summary_run.status,
            "error_message": summary_run.error_message,
        }
        if summary_run
        else None,
        "messages": [
            {
                **message_dict(m),
                "run_status": runs[m.run_id].status if m.run_id in runs else None,
                "error_message": runs[m.run_id].error_message if m.run_id in runs else "",
                **task_results(session, m, runs.get(m.run_id)),
                **(
                    {"agent_control_run": linked}
                    if (linked := linked_run(session, m, runs.get(m.run_id)))
                    else {}
                ),
            }
            for m in reversed(messages)
        ],
        "active_run": run_dict(active) if active else None,
        "summary": summary_view(session, row.id),
        "work_context": project_context(session, row.id),
    }


class WorkSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID | None
    expected_run_id: UUID | None = None
    expected_settings_version: int = Field(ge=1)

    @model_validator(mode="after")
    def matching_source(self):
        if (self.task_id is None) != (self.expected_run_id is None):
            raise ValueError("Choose a coding task with its current proposal")
        return self


@router.put("/conversations/{conversation_id}/work-context")
def choose_work_task(conversation_id: UUID, body: WorkSelection, session: DB):
    from app.work_context import context_of, selected_source

    row = conversation(session, conversation_id)
    ensure_idle(session, row.id)
    if body.task_id:
        task, source = selected_source(session, body.task_id, body.expected_run_id)
        selected = context_of(session, source)
    else:
        selected = None
    result = session.execute(
        update(Conversation)
        .where(Conversation.id == row.id, Conversation.settings_version == body.expected_settings_version)
        .values(settings_version=Conversation.settings_version + 1, updated_at=utcnow())
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Conversation settings changed; reload before selecting")
    binding = session.get(ChatWorkContext, row.id)
    if binding is None:
        binding = ChatWorkContext(conversation_id=row.id)
        session.add(binding)
    binding.task_id = str(body.task_id) if body.task_id else None
    binding.selected_at = utcnow()
    session.commit()
    session.refresh(row)
    return {"work_context": selected, "settings_version": row.settings_version}


@router.post("/conversations/{conversation_id}/tasks/{task_id}/cancel")
def stop_conversation_task(conversation_id: UUID, task_id: UUID, session: DB):
    from app.task_control import cancel_task

    row = conversation(session, conversation_id)
    task = session.get(Task, str(task_id))
    binding = session.get(ChatWorkContext, row.id)
    if task is None or not (
        task.conversation_id == row.id
        or binding is not None
        and binding.task_id == task.id
        or session.scalar(
            select(Run.id).where(Run.task_id == task.id, Run.conversation_id == row.id).limit(1)
        )
    ):
        raise HTTPException(404, "Task not found in this conversation")
    result = cancel_task(session, task)
    session.commit()
    return result


def enqueue(
    session,
    row,
    *,
    user: Message,
    parent_run_id=None,
    commit=True,
    frozen_provider=None,
    reserve_context=0,
    operation_key=None,
):
    if type(reserve_context) is not int or not 0 <= reserve_context <= 20000:
        raise ValueError("Invalid reserved conversation context")
    snapshot = dict(frozen_provider) if frozen_provider is not None else snapshot_provider(session, row)
    from app.chat_pages import freeze_page_read, prepare_page_browser
    from app.web_search import conversation_query_context

    web_search = user.metadata_json.get("web_search")
    summary = latest_summary(session, row.id)
    summary_entry = summary_memory(session, summary)
    history = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == row.id, Message.created_at <= user.created_at)
            .where(uncovered_since(summary, summary_entry))
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(200)
        )
    )
    context = []
    transcript_sources = []
    agent_result_sources = []
    agent_result_seen = set()
    transcript_budget = 20000
    budget = 56000 - reserve_context
    for message in history:
        if (
            message.metadata_json.get("superseded")
            or message.role == "assistant"
            and message.metadata_json.get("partial", False)
        ):
            continue
        if message.role not in {"user", "assistant"}:
            continue
        content = uncovered_text(message, summary, summary_entry)
        if not content:
            continue
        if len(content) + 2 > budget or len(context) >= 16:
            break
        if message.metadata_json.get("orchestration") and message.run_id:
            result = task_results(session, message, session.get(Run, message.run_id))
            content += "\nRecorded task results: " + str(result.get("steps", []))[:8000]
            from app.transcript_context import reference

            quoted = reference(
                session, message, budget=min(transcript_budget, max(0, budget - len(content) - 2))
            )
            if quoted:
                content += quoted[0]
                transcript_sources.append(quoted[1])
                transcript_budget -= len(quoted[0])
        from app.agent_result_context import reference as agent_result_reference

        agent_result = agent_result_reference(
            session, message, budget=min(12000, max(0, budget - len(content) - 2))
        )
        if agent_result and agent_result[1]["agent_id"] not in agent_result_seen:
            content += agent_result[0]
            agent_result_sources.append(agent_result[1])
            agent_result_seen.add(agent_result[1]["agent_id"])
        if len(content) + 2 > budget:
            break
        context.append({"role": message.role, "content": content, "_message_id": message.id})
        budget -= len(content) + 2
    context.reverse()
    # A window may begin midway through a turn. Templates commonly require
    # user/assistant alternation after the optional system message.
    while context and context[0]["role"] == "assistant":
        context.pop(0)
    retained_messages = {item.pop("_message_id") for item in context}
    transcript_sources = [
        source for source in transcript_sources if source["source_message_id"] in retained_messages
    ]
    agent_result_sources = [
        source for source in agent_result_sources if source["source_message_id"] in retained_messages
    ]
    alternating = []
    for item in context:
        if alternating and alternating[-1]["role"] == item["role"]:
            alternating[-1]["content"] += "\n\n" + item["content"]
        else:
            alternating.append(item)
    context = alternating
    pinned = list(
        session.scalars(
            select(MemoryEntry)
            .where(
                MemoryEntry.enabled.is_(True),
                MemoryEntry.pinned.is_(True),
                ((MemoryEntry.scope == "conversation") & (MemoryEntry.scope_id == row.id))
                | ((MemoryEntry.scope == "global") & (MemoryEntry.scope_id == "")),
            )
            .order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id)
            .limit(20)
        )
    )
    memory_context, memory_sources = [], []
    memory_budget = 12000
    for entry in pinned:
        if len(entry.content) > memory_budget:
            continue
        memory_context.append(f"[{entry.scope}/{entry.memory_type}] {entry.content}")
        memory_sources.append({"id": entry.id, "updated_at": entry.updated_at.isoformat()})
        memory_budget -= len(entry.content)
    system = row.system_prompt
    if summary_entry:
        system += (
            "\n\nEarlier conversation summary (reference only; may be imperfect):\n" + summary_entry.content
        )
    if memory_context:
        system += "\n\nUser-pinned reference context (may be outdated):\n" + "\n\n".join(memory_context)
    if system:
        context.insert(0, {"role": "system", "content": system.strip()})
    intent = user.metadata_json.get("user_text", user.content)
    parent = session.get(Run, parent_run_id) if parent_run_id else None
    task = (
        session.get(Task, parent.task_id)
        if parent
        else create_task(
            session,
            title=intent[:80],
            prompt=intent,
            capability="chat.completion",
            intent="chat",
            conversation_id=row.id,
        )
    )
    page_read = freeze_page_read(session, row.id, user, web_search)
    run = create_run(
        session,
        task,
        run_type="chat",
        capability="chat.completion",
        operation_key=operation_key,
        executor_type="chat",
        execution_target="container",
        parameters={
            "web_search": web_search,
            "page_read": page_read,
            **(
                {"web_search_context": conversation_query_context(session, row.id, user)}
                if web_search and web_search.get("contextual")
                else {}
            ),
            "execution_mode": "local",
            "policy_mode": policy_mode(user.metadata_json.get("execution_mode", "local")),
            "policy_version": POLICY_VERSION,
            **snapshot,
            "model": row.model,
            "temperature": row.temperature,
            "max_tokens": row.max_tokens,
            **(
                {
                    "reasoning": user.metadata_json["reasoning"],
                    "reasoning_certificate": user.metadata_json["reasoning_certificate"],
                }
                if user.metadata_json.get("reasoning") is not None
                else {}
            ),
            "messages": context,
            "memory_sources": memory_sources,
            **(
                {"agent_result_sources": list(reversed(agent_result_sources))} if agent_result_sources else {}
            ),
            **({"transcript_sources": list(reversed(transcript_sources))} if transcript_sources else {}),
            "summary_source": {
                "id": summary.id,
                "memory_id": summary_entry.id,
                "updated_at": iso(summary_entry.updated_at),
            }
            if summary_entry
            else None,
        },
        permissions=chat_permissions(
            snapshot,
            (["network_read"] if web_search else [])
            + (["browser"] if page_read and page_read.get("renderer") == "browser" else []),
        ),
        retry_class="inspect",
        parent_run_id=parent_run_id,
    )
    from app.llama import prepare_consumer

    prepare_page_browser(session, run)
    prepare_consumer(session, run)
    response = Message(
        conversation_id=row.id,
        role="assistant",
        content="",
        run_id=run.id,
        metadata_json={
            "partial": True,
            **(
                {"page_read_request": run.parameters["page_read"]["urls"]}
                if run.parameters.get("page_read", {}) and run.parameters["page_read"].get("urls")
                else {}
            ),
            **({"transcript_sources": list(reversed(transcript_sources))} if transcript_sources else {}),
            **(
                {"agent_result_sources": list(reversed(agent_result_sources))} if agent_result_sources else {}
            ),
        },
    )
    session.add(response)
    if user.run_id is None:
        user.run_id = run.id
        link_attachments(session, user, run)
    row.updated_at = utcnow()
    if row.title == "New conversation":
        row.title = intent[:80]
    if commit:
        session.commit()
    return run_dict(run)


@router.post("/conversations/{conversation_id}/messages", status_code=202)
def send(conversation_id: UUID, body: MessageBody, session: DB):
    return submit_message(conversation_id, body, session)


def submit_message(conversation_id, body, session, *, commit=True):
    row = conversation(session, conversation_id)
    ensure_idle(session, row.id)
    mode = turn_execution_mode(row, body)
    from app.conversation_agent_control import prepare as prepare_agent_control

    body, agent_control = prepare_agent_control(session, row, body, mode)
    from app.conversation_data import prepare_turn as prepare_data_turn
    from app.conversation_music import prepare_turn
    from app.selected_data_agent import prepare as prepare_selected_agent

    body, selected_data_agent = prepare_selected_agent(session, row, body, mode)
    body = prepare_data_turn(body)
    from app.conversation_data_reference import resolve as resolve_data_reference

    body, data_reference = resolve_data_reference(session, row, body, mode)
    from app.data_agent_draft import resolve as resolve_data_agent

    body, data_agent_source = resolve_data_agent(session, row, body, mode)
    from app.file_creation import prepare_turn as prepare_file_creation

    work_context = session.get(ChatWorkContext, row.id)
    if work_context is None or not work_context.task_id:
        body = prepare_file_creation(body, mode)
    if mode in {"chat", "work", "orchestrator"}:
        body = prepare_turn(body)
    from app.conversation_media import resolve_result_reference

    body, result_reference = resolve_result_reference(session, row, body, mode)
    result_reference = data_reference or result_reference
    if mode == "chat":
        validate_chat_scope(body)
    from app.project_reference import resolve_project_reference

    body, project_reference = resolve_project_reference(session, body, mode)
    use_assistant = (
        mode in {"orchestrator", "work"}
        or mode == "chat"
        and (
            body.action not in {"auto", "chat"}
            or body.image_artifact_ids
            or body.audio_artifact_id
            or explicit_plan(body.model_dump(mode="json", exclude={"attachments"})) is not None
        )
    )
    if mode in {"chat", "work"}:
        body = body.model_copy(update={"execution_mode": mode})
    # Deterministic host inspection/runtime control does not contact an LLM.
    if (
        agent_control is None
        and body.continuation is None
        and (not use_assistant or assistant_needs_provider(body))
    ):
        snapshot_provider(session, row)  # Validate the selected provider before attachments.
    user = Message(
        conversation_id=row.id,
        role="user",
        content=message_content(body.content, body.attachments),
        metadata_json={"user_text": body.content} if body.attachments else {},
    )
    if selected_data_agent:
        user.metadata_json = {**user.metadata_json, "selected_data_agent": selected_data_agent}
    if data_agent_source:
        user.metadata_json = {**user.metadata_json, "data_agent_source": data_agent_source}
    if result_reference:
        user.metadata_json = {**user.metadata_json, "conversation_reference": result_reference}
    if project_reference:
        user.metadata_json = {**user.metadata_json, "project_reference": project_reference}
    if body.reasoning is not None:
        from app.chat_reasoning import certificate, validated_options

        if use_assistant or body.action not in {"auto", "chat"} or mode not in {"chat", "local"}:
            raise HTTPException(
                422, "Thinking controls apply to Chat replies; Work uses its executor policies"
            )
        options = validated_options(session, row.model, body.reasoning, row.max_tokens)
        user.metadata_json = {
            **user.metadata_json,
            "reasoning": options,
            "reasoning_certificate": certificate(session, row.model),
        }
    from app.web_search import selection

    try:
        search_options = selection(body.web_search, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if search_options:
        user.metadata_json = {**user.metadata_json, "web_search": search_options}
    session.add(user)
    session.flush()
    user.metadata_json = {
        **user.metadata_json,
        "execution_mode": mode,
        "execution_mode_override": body.execution_mode,
    }
    if agent_control is not None:
        from app.conversation_agent_control import enqueue as enqueue_agent_control

        result = enqueue_agent_control(session, row, user, body, agent_control)
    elif body.continuation is not None:
        from app.work_context import enqueue_continuation

        result = enqueue_continuation(session, row, user, body)
    elif use_assistant:
        result = enqueue_assistant(session, row, user, body, commit=False)
    elif (
        body.image_artifact_ids
        or body.audio_artifact_id
        or body.github
        or body.music
        or body.action not in {"auto", "chat"}
        or body.coding
        or body.commit
        or body.publish
        or body.load
        or body.stop
    ):
        raise HTTPException(422, "Select Platform assistant for this turn to use capability actions")
    else:
        result = enqueue(session, row, user=user, commit=False)
    if body.attachments:
        user.metadata_json = {
            **user.metadata_json,
            "attachments": save_attachments(session, user, body.attachments),
        }
        link_attachments(session, user, session.get(Run, result["id"]))
    if commit:
        session.commit()
    return result


class TurnBody(MessageBody):
    client_request_id: UUID
    conversation_id: UUID | None = None
    selection: ConversationBody | None = None
    expected_settings_version: int | None = Field(default=None, ge=1)
    expected_provider_version: AwareDatetime | None = None

    @model_validator(mode="after")
    def selection_scope(self):
        if self.conversation_id is None and self.selection is None:
            raise ValueError("Select a model for the new conversation")
        if self.conversation_id is not None and self.selection is not None:
            raise ValueError("Save conversation settings before sending")
        if self.conversation_id is not None and self.expected_settings_version is None:
            raise ValueError("Include the current conversation settings version")
        return self


@router.post("/turns", status_code=202)
def accept_turn(body: TurnBody, session: DB):
    payload = body.model_dump(mode="json")
    if body.analysis_agent_source_run_id is None:
        payload.pop("analysis_agent_source_run_id")
    if body.expected_provider_version is None:
        payload.pop("expected_provider_version")
    if body.reasoning is None:
        payload.pop("reasoning")
    if body.continuation is None:
        payload.pop("continuation")
    if body.media is None:
        payload.pop("media")
    if body.music is None:
        payload.pop("music")
    if body.data is None:
        payload.pop("data")
    if body.github is None:
        payload.pop("github")
    if body.project_defaults is None:
        payload.pop("project_defaults")
    if body.schedule_timezone is None:
        payload.pop("schedule_timezone")

    def fingerprint(values):
        return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    digest = fingerprint(payload)
    receipt = session.get(ChatTurnRequest, str(body.client_request_id))
    if receipt:
        hashes = {digest}
        scope = payload.get("new_project")
        if (
            isinstance(scope, dict)
            and not scope.get("auto_install_dependencies")
            and not scope.get("auto_validate")
        ):
            legacy = {
                key: value
                for key, value in scope.items()
                if key not in {"auto_install_dependencies", "auto_validate"}
            }
            hashes.add(fingerprint({**payload, "new_project": legacy}))
        # Before #273, receipts did not include the optional new-project scope.
        if payload.get("new_project") is None:
            hashes.add(fingerprint({key: value for key, value in payload.items() if key != "new_project"}))
        if receipt.payload_hash not in hashes:
            raise HTTPException(409, "This request ID already belongs to a different message")
        return turn_receipt(session, receipt)
    if body.conversation_id:
        row = conversation(session, body.conversation_id)
        if row.settings_version != body.expected_settings_version:
            raise HTTPException(409, "Conversation settings changed; refresh before sending")
    else:
        selection = body.selection
        if body.expected_provider_version is not None:
            from app.chat_providers import get_provider

            if get_provider(session, selection.provider).updated_at != body.expected_provider_version:
                raise HTTPException(409, "Provider configuration changed; choose the model again")
        if body.continuation:
            if selection.provider != BUILTIN_KEY or selection.execution_mode not in {"work", "orchestrator"}:
                raise HTTPException(
                    422, "Open the selected coding task in Work using local conversation settings"
                )
            from app.work_context import selected_source

            selected_task, _ = selected_source(
                session, body.continuation.task_id, body.continuation.expected_run_id
            )
        else:
            snapshot_provider(session, Conversation(provider=selection.provider, model=selection.model))
        row = Conversation(**selection.model_dump())
        session.add(row)
        session.flush()
        if body.continuation:
            session.add(ChatWorkContext(conversation_id=row.id, task_id=selected_task.id))
            session.flush()
    if body.conversation_id and body.expected_provider_version is not None:
        from app.chat_providers import get_provider

        if get_provider(session, row.provider).updated_at != body.expected_provider_version:
            raise HTTPException(409, "Provider configuration changed; choose the model again")
    message = MessageBody.model_validate({key: getattr(body, key) for key in MessageBody.model_fields})
    result = submit_message(row.id, message, session, commit=False)
    session.flush()
    user = session.scalar(select(Message).where(Message.run_id == result["id"], Message.role == "user"))
    receipt = ChatTurnRequest(
        id=str(body.client_request_id),
        payload_hash=digest,
        conversation_id=row.id,
        user_message_id=user.id,
        task_id=result["task_id"],
        run_id=result["id"],
    )
    session.add(receipt)
    if body.conversation_id is None:
        saved = session.get(Setting, "conversation_preferences")
        previous = ChatPreferences.model_validate(saved.value if saved else {})
        values = previous.model_copy(
            update={
                "version": previous.version + 1,
                "mode": policy_mode(row.execution_mode),
                "provider": row.provider,
                "model": row.model,
            }
        ).model_dump()
        if saved is None:
            session.add(Setting(key="conversation_preferences", value=values))
        else:
            saved.value = values
    session.commit()
    return turn_receipt(session, receipt)


def turn_receipt(session, receipt):
    return {
        "conversation_id": receipt.conversation_id,
        "user_message_id": receipt.user_message_id,
        "task_id": receipt.task_id,
        "run": run_dict(session.get(Run, receipt.run_id)),
    }


class ChatPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(default=0, ge=0)
    mode: Literal["chat", "work"] = "chat"
    provider: str = Field(default=BUILTIN_KEY, min_length=1, max_length=80)
    model: str = Field(default="", max_length=200)
    send_key: Literal["enter", "ctrl-enter"] = "enter"
    web_search_enabled: bool = True


@router.get("/preferences")
def preferences(session: DB):
    row = session.get(Setting, "conversation_preferences")
    return ChatPreferences.model_validate(row.value if row else {}).model_dump()


@router.put("/preferences")
def save_preferences(body: ChatPreferences, session: DB):
    row = session.get(Setting, "conversation_preferences")
    current = ChatPreferences.model_validate(row.value if row else {})
    if current.version != body.version:
        raise HTTPException(409, "Preferences changed; refresh before saving")
    if body.model:
        snapshot_provider(session, Conversation(provider=body.provider, model=body.model))
    updates = {"version": current.version + 1}
    if "web_search_enabled" not in body.model_fields_set:
        updates["web_search_enabled"] = current.web_search_enabled
    values = body.model_copy(update=updates).model_dump()
    if row is None:
        row = Setting(key="conversation_preferences", value=values)
        session.add(row)
    else:
        row.value = values
    session.commit()
    return values


@router.post("/conversations/{conversation_id}/regenerate", status_code=202)
def regenerate(conversation_id: UUID, session: DB):
    row = conversation(session, conversation_id)
    ensure_idle(session, row.id)
    user = session.scalar(
        select(Message)
        .where(Message.conversation_id == row.id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if user is None:
        raise HTTPException(409, "There is no user message to regenerate")
    source_run = session.get(Run, user.run_id) if user.run_id else None
    if source_run and source_run.executor_type == "orchestrator":
        raise HTTPException(409, "Send a new instruction to repeat an assistant action explicitly")
    if source_run:
        from app.task_control import lock_task

        task = session.get(Task, source_run.task_id)
        lock_task(session, task)
        if task.metadata_json.get("stop_requested_at"):
            if source_run.executor_type != "chat" or session.scalar(
                select(Run.id).where(Run.task_id == task.id, Run.status.not_in(TERMINAL)).limit(1)
            ):
                raise HTTPException(409, "Wait for stopped work to finish or send a new instruction")
            # Regenerate is an explicit new attempt after every old stage ended.
            task.metadata_json = {
                key: value for key, value in task.metadata_json.items() if key != "stop_requested_at"
            }
    responses = list(
        session.scalars(
            select(Message)
            .where(
                Message.conversation_id == row.id,
                Message.role == "assistant",
                Message.created_at >= user.created_at,
            )
            .order_by(Message.created_at)
        )
    )
    for response in responses:
        response.metadata_json = {**response.metadata_json, "superseded": True}
    return enqueue(session, row, user=user, parent_run_id=responses[-1].run_id if responses else None)


@router.post("/conversations/{conversation_id}/summarize", status_code=202)
def summarize(conversation_id: UUID, session: DB):
    row = conversation(session, conversation_id)
    ensure_idle(session, row.id)
    return enqueue_summary(session, row, snapshot_provider(session, row))
