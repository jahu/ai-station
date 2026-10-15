"""Publish an ordinary Chat answer only after a verified local transcription."""

from fastapi import HTTPException
from sqlalchemy import select

from app.chat_providers import chat_permissions, normalize_provider_key, require_external_permission
from app.events import append_event
from app.models import Conversation, Message, Run
from app.providers import ProviderError
from app.runs import create_run, mark_failed, transition
from app.state import RunStatus
from app.task_control import lock_task
from app.transcript_context import reference

PROVIDER_FIELDS = ("provider", "provider_id", "location", "endpoint", "secret_ref", "provider_config_version")


def publish_answer(session, transcription):
    lock_task(session, transcription.task)
    if transcription.task.metadata_json.get("stop_requested_at"):
        append_event(session, transcription.id, "workflow.answer.skipped", {"reason": "Task was stopped"})
        return
    key = "audio.answer/" + transcription.id
    existing = session.scalar(
        select(Run).where(Run.task_id == transcription.task_id, Run.operation_key == key)
    )
    if existing:
        transcription.metadata_json = {**transcription.metadata_json, "answer_run_id": existing.id}
        return
    parent = session.get(Run, transcription.parent_run_id)
    if (
        transcription.status != "succeeded"
        or parent is None
        or parent.executor_type != "orchestrator"
        or parent.status != "succeeded"
        or parent.task_id != transcription.task_id
        or parent.conversation_id != transcription.conversation_id
        or parent.metadata_json.get("plan", {}).get("action") != "audio.analyze"
    ):
        raise ValueError("Recording answer does not belong to a completed analysis stage")
    user = session.get(Message, parent.parameters["user_message_id"])
    message = session.scalar(select(Message).where(Message.run_id == parent.id, Message.role == "assistant"))
    conversation = session.get(Conversation, transcription.conversation_id)
    if user is None or message is None or conversation is None or user.conversation_id != conversation.id:
        raise ValueError("Recording answer conversation ownership changed")
    if not transcription.metadata_json["transcription"]["text"].strip():
        message.content = "No speech was detected in this recording. Try a clearer recording or choose its language in Audio."
        transcription.metadata_json = {**transcription.metadata_json, "answer_skipped_reason": "no_speech"}
        append_event(session, transcription.id, "workflow.answer.skipped", {"reason": "No speech detected"})
        return
    frozen = {name: parent.parameters[name] for name in PROVIDER_FIELDS}
    settings = parent.parameters["audio_answer_settings"]
    require_external_permission(parent)
    try:
        with session.begin_nested():
            if (
                conversation.model != settings["model"]
                or conversation.temperature != settings["temperature"]
                or conversation.max_tokens != settings["max_tokens"]
                or normalize_provider_key(conversation.provider) != frozen["provider"]
            ):
                raise ProviderError("Conversation model settings changed during transcription")
            quoted = reference(session, message)
            if not quoted or not quoted[1]["available"] or quoted[1].get("run_id") != transcription.id:
                raise ProviderError("The completed transcript is unavailable for this answer")
            from app.chat import enqueue

            result = enqueue(
                session,
                conversation,
                user=user,
                parent_run_id=transcription.id,
                commit=False,
                frozen_provider=frozen,
                reserve_context=20000,
                operation_key=key,
            )
            answer = session.get(Run, result["id"])
            messages = [dict(item) for item in answer.parameters["messages"]]
            if not messages or messages[-1]["role"] != "user":
                raise ProviderError("Recording answer has no original user question")
            messages[-1]["content"] += quoted[0]
            sources = [*answer.parameters.get("transcript_sources", []), quoted[1]]
            answer.parameters = {
                **answer.parameters,
                "messages": messages,
                "transcript_sources": sources,
                "audio_analysis_source_run_id": transcription.id,
            }
            response = session.scalar(
                select(Message).where(Message.run_id == answer.id, Message.role == "assistant")
            )
            response.metadata_json = {**response.metadata_json, "transcript_sources": sources}
            append_event(session, answer.id, "context.transcript", quoted[1])
    except (HTTPException, ProviderError, ValueError) as exc:
        reason = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        answer = create_run(
            session,
            transcription.task,
            run_type="chat",
            capability="chat.completion",
            executor_type="chat",
            execution_target="container",
            parent_run_id=transcription.id,
            operation_key=key,
            permissions=chat_permissions(frozen),
            retry_class="inspect",
            parameters={**frozen, **settings, "audio_analysis_source_run_id": transcription.id},
        )
        answer.worker_id = transcription.worker_id
        transition(
            session, answer, RunStatus.CLAIMED, event_type="run.claimed", payload={"preparation_only": True}
        )
        mark_failed(session, answer, "AudioAnswerPreparationFailed", reason)
        session.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content="",
                run_id=answer.id,
                metadata_json={"partial": False},
            )
        )
    transcription.metadata_json = {**transcription.metadata_json, "answer_run_id": answer.id}
    append_event(
        session,
        transcription.id,
        "workflow.step.failed" if answer.status == "failed" else "workflow.step.queued",
        {"run_id": answer.id, "capability": answer.capability, "status": answer.status},
    )
