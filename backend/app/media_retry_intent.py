"""Explicit media retries may start a new intent without reopening a stopped Task."""

from uuid import UUID

from fastapi import HTTPException

from app.db import utcnow
from app.events import append_event
from app.models import Conversation, Message, Run
from app.runs import create_task
from app.task_control import lock_task

FRESH = "fresh_media_retry"
SOURCE = "fresh_retry_source"
REUSED = "reused_from_run_id"


def locked_source(session, source):
    lock_task(session, source.task)
    session.refresh(source)
    if source.status not in {"failed", "canceled", "interrupted"}:
        raise HTTPException(409, "The original media Run changed; inspect it before retrying")


def existing_fresh(session, source, identity, *, replayable):
    reference = source.metadata_json.get(FRESH)
    if reference is None:
        return None
    valid = (
        isinstance(reference, dict)
        and set(reference) == {"run_id", "task_id", "request"}
        and isinstance(reference.get("request"), dict)
        and set(reference["request"]) == {"id", "translation"}
        and reference["request"].get("translation") in {"reuse", "retry", "original"}
    )
    if valid:
        try:
            valid = all(str(UUID(reference[key])) == reference[key] for key in ("run_id", "task_id"))
        except (ValueError, TypeError, AttributeError):
            valid = False
    child = session.get(Run, reference["run_id"]) if valid else None
    origin = {"run_id": source.id, "task_id": source.task_id}
    if not (
        child
        and source.status in {"failed", "canceled", "interrupted"}
        and source.task.metadata_json.get("stop_requested_at")
        and child.metadata_json.get(
            "image_retry_request" if source.executor_type == "photo_pipe" else "media_retry_request"
        )
        == reference["request"]
        and child.task.metadata_json.get("translation_choice") == reference["request"]["translation"]
        and child.task_id == reference["task_id"] != source.task_id
        and child.parent_run_id is None
        and child.metadata_json.get(SOURCE) == origin
        and child.task.metadata_json.get(SOURCE) == origin
        and child.task.conversation_id == child.conversation_id == source.conversation_id
        and child.task.project_id == child.project_id == source.project_id
        and child.task.agent_id == child.agent_id == source.agent_id
        and child.executor_type == source.executor_type
        and child.capability == source.capability
        and child.execution_target == source.execution_target
        and child.effective_permissions == source.effective_permissions
    ):
        raise HTTPException(409, "The new media attempt needs inspection; no work was repeated")
    if not replayable or reference["request"] != identity:
        raise HTTPException(409, "A new attempt already exists; inspect that Run instead")
    return child


def task_for_retry(session, source, choice):
    """Caller holds the original Task lock after inspecting its native process."""
    old = source.task
    if not old.metadata_json.get("stop_requested_at"):
        return old
    if source.conversation_id != old.conversation_id:
        raise HTTPException(409, "Media conversation ownership needs inspection")
    if source.conversation_id:
        conversation = session.get(Conversation, source.conversation_id)
        if conversation is None or conversation.archived_at is not None:
            raise HTTPException(409, "Restore the original conversation before starting a new attempt")
    return create_task(
        session,
        title=old.title,
        prompt=old.prompt,
        capability=source.capability,
        intent=source.capability,
        project_id=source.project_id,
        conversation_id=source.conversation_id,
        agent_id=source.agent_id,
        metadata={SOURCE: {"run_id": source.id, "task_id": old.id}, "translation_choice": choice},
    )


def finish_retry(session, source, retry, identity):
    if retry.task_id == source.task_id:
        source.metadata_json = {**source.metadata_json, "retry_run_id": retry.id}
        return
    origin = {"run_id": source.id, "task_id": source.task_id}
    receipt = retry.metadata_json.get("prompt_translation")
    retry.metadata_json = {
        **retry.metadata_json,
        SOURCE: origin,
        **(
            {"prompt_translation": {**receipt, REUSED: source.id}}
            if identity["translation"] == "reuse" and receipt and receipt.get("status") == "ready"
            else {}
        ),
    }
    source.metadata_json = {
        **source.metadata_json,
        FRESH: {"run_id": retry.id, "task_id": retry.task_id, "request": identity},
    }
    append_event(
        session, source.id, "media.fresh_retry.created", {"run_id": retry.id, "task_id": retry.task_id}
    )
    append_event(session, retry.id, "media.fresh_retry.origin", origin)
    if retry.conversation_id is None:
        return
    conversation = session.get(Conversation, retry.conversation_id)
    if conversation is None:
        raise HTTPException(409, "The original conversation is unavailable")
    action = {
        "original": "Use original prompt in a new task.",
        "retry": "Retry prompt translation in a new task.",
        "reuse": "Retry this media request in a new task.",
    }[identity["translation"]]
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=action,
            run_id=retry.id,
            metadata_json={SOURCE: origin},
        )
    )
    session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=f"Started a new attempt from the [earlier run](#/runs/{source.id}). The earlier task remains stopped.",
            run_id=retry.id,
            metadata_json={"orchestration": True, SOURCE: origin},
        )
    )
    conversation.updated_at = utcnow()


def reuse_source(session, run, identifier):
    """Only a bound fresh intent may reuse another Task's verified translation."""
    origin = run.task.metadata_json.get(SOURCE)
    source = session.get(Run, identifier) if isinstance(identifier, str) else None
    if not source or origin != {"run_id": source.id, "task_id": source.task_id}:
        raise ValueError("Translation reuse has no matching fresh intent")
    reference = source.metadata_json.get(FRESH)
    if not isinstance(reference, dict):
        raise ValueError("Translation reuse has no source receipt")
    try:
        root = existing_fresh(session, source, reference.get("request"), replayable=True)
    except HTTPException as exc:
        raise ValueError("Translation reuse ownership changed") from exc
    if not root or any(
        getattr(root, key) != getattr(run, key)
        for key in (
            "task_id",
            "executor_type",
            "capability",
            "execution_target",
            "conversation_id",
            "effective_permissions",
        )
    ):
        raise ValueError("Translation reuse belongs to a different media intent")
    return source
