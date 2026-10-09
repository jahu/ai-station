"""Conversation intent, immutable run context, and inspectable message history."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant import AssistantInputs, enqueue_assistant, task_results
from app.chat_attachments import TextAttachment, link_attachments, message_content, save_attachments
from app.chat_providers import BUILTIN_KEY, chat_permissions, snapshot_provider
from app.conversation_summary import (
    enqueue_summary,
    latest_summary,
    summary_memory,
    summary_view,
    uncovered_since,
    uncovered_text,
)
from app.db import session_scope, utcnow
from app.models import Conversation, MemoryEntry, Message, ModelFile, Run, Task
from app.runs import create_run, create_task, run_dict
from app.serialize import conversation_dict, iso, message_dict
from app.state import TERMINAL

router = APIRouter(prefix="/api/chat")
DB = Annotated[Session, Depends(session_scope)]


class ConversationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    execution_mode: Literal["local", "orchestrator"] = "local"
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
    execution_mode: Literal["auto", "local", "orchestrator"] = "auto"

    @model_validator(mode="after")
    def validate_context(self):
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
        "provider_name": provider.name if provider else row.provider,
        "provider_location": provider.location if provider else "local",
    }


def ensure_idle(session, conversation_id):
    active = session.scalar(
        select(Run).where(Run.conversation_id == conversation_id, Run.status.not_in(TERMINAL))
    )
    if active is not None:
        raise HTTPException(409, "This conversation already has an active run")


@router.get("/conversations")
def conversations(session: DB):
    from app.chat_providers import ensure_builtin

    ensure_builtin(session)
    session.commit()
    return [
        conversation_view(session, row)
        for row in session.scalars(select(Conversation).order_by(Conversation.updated_at.desc()).limit(100))
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
    session.commit()
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
            }
            for m in reversed(messages)
        ],
        "active_run": run_dict(active) if active else None,
        "summary": summary_view(session, row.id),
    }


def enqueue(session, row, *, user: Message, parent_run_id=None, commit=True):
    snapshot = snapshot_provider(session, row)
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
    budget = 56000
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
        if len(content) + 2 > budget:
            break
        context.append({"role": message.role, "content": content})
        budget -= len(content) + 2
    context.reverse()
    # A window may begin midway through a turn. Templates commonly require
    # user/assistant alternation after the optional system message.
    while context and context[0]["role"] == "assistant":
        context.pop(0)
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
    run = create_run(
        session,
        task,
        run_type="chat",
        capability="chat.completion",
        executor_type="chat",
        execution_target="container",
        parameters={
            "web_search": web_search,
            "execution_mode": "local",
            **snapshot,
            "model": row.model,
            "temperature": row.temperature,
            "max_tokens": row.max_tokens,
            "messages": context,
            "memory_sources": memory_sources,
            "summary_source": {
                "id": summary.id,
                "memory_id": summary_entry.id,
                "updated_at": iso(summary_entry.updated_at),
            }
            if summary_entry
            else None,
        },
        permissions=chat_permissions(snapshot, ["network_read"] if web_search else []),
        retry_class="inspect",
        parent_run_id=parent_run_id,
    )
    from app.llama import prepare_consumer

    prepare_consumer(session, run)
    response = Message(
        conversation_id=row.id, role="assistant", content="", run_id=run.id, metadata_json={"partial": True}
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
    row = conversation(session, conversation_id)
    ensure_idle(session, row.id)
    snapshot_provider(session, row)  # Validate the selected provider before attachments.
    user = Message(
        conversation_id=row.id,
        role="user",
        content=message_content(body.content, body.attachments),
        metadata_json={"user_text": body.content} if body.attachments else {},
    )
    from app.web_search import selection

    try:
        search_options = selection(body.web_search, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if search_options:
        user.metadata_json = {**user.metadata_json, "web_search": search_options}
    session.add(user)
    session.flush()
    if body.attachments:
        user.metadata_json = {
            **user.metadata_json,
            "attachments": save_attachments(session, user, body.attachments),
        }
    mode = turn_execution_mode(row, body)
    user.metadata_json = {
        **user.metadata_json,
        "execution_mode": mode,
        "execution_mode_override": body.execution_mode,
    }
    if mode == "orchestrator":
        return enqueue_assistant(session, row, user, body)
    if (
        body.image_artifact_ids
        or body.audio_artifact_id
        or body.action != "auto"
        or body.coding
        or body.commit
        or body.publish
        or body.load
        or body.stop
    ):
        raise HTTPException(422, "Select Platform assistant for this turn to use capability actions")
    return enqueue(session, row, user=user)


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
    if user.metadata_json.get("execution_mode", row.execution_mode) == "orchestrator":
        raise HTTPException(409, "Send a new instruction to repeat an assistant action explicitly")
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
