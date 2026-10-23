"""Resolve selected inputs from a completed Vision result, never from model prose."""

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Artifact, Message, Run
from app.paths import artifact_relative
from app.python_execution import read_owned_file
from app.vision_inputs import verify


def inspected_inputs(session, source, root_message):
    ids = source.parameters.get("image_artifact_ids") or []
    if not ids:
        return None
    error = "The latest inspected image is unavailable or unverified. Reattach it or inspect it again."
    child = session.get(Run, source.metadata_json.get("child_run_id", ""))
    user = session.get(Message, source.parameters.get("user_message_id", ""))
    inputs = source.parameters.get("image_inputs")
    if (
        source.executor_type != "orchestrator"
        or source.status != "succeeded"
        or root_message.metadata_json.get("partial")
        or not isinstance(inputs, list)
        or any(not isinstance(item, dict) for item in inputs)
        or [item.get("artifact_id") for item in inputs] != ids
        or user is None
        or user.role != "user"
        or user.run_id != source.id
        or user.conversation_id != source.conversation_id
        or [item.get("id") for item in user.metadata_json.get("images", [])] != ids
        or child is None
        or child.capability != "chat.vision"
        or child.executor_type != "chat"
        or child.status != "succeeded"
        or child.parent_run_id != source.id
        or child.task_id != source.task_id
        or child.conversation_id != source.conversation_id
        or child.parameters.get("vision_artifact_ids") != ids
        or child.parameters.get("vision_inputs") != inputs
    ):
        raise HTTPException(422, error)
    messages = list(
        session.scalars(
            select(Message)
            .where(
                Message.run_id == child.id,
                Message.conversation_id == source.conversation_id,
                Message.role == "assistant",
            )
            .limit(2)
        )
    )
    results = list(
        session.scalars(
            select(Artifact)
            .where(
                Artifact.run_id == child.id,
                Artifact.artifact_type == "markdown",
            )
            .limit(2)
        )
    )
    if (
        len(messages) != 1
        or any(messages[0].metadata_json.get(key) for key in ("partial", "superseded", "routing_only"))
        or len(results) != 1
        or results[0].trashed_at is not None
        or results[0].parent_artifact_ids != ids
        or results[0].metadata_json.get("operation") != "image.describe"
        or results[0].metadata_json.get("vision_inputs") != inputs
        or results[0].relative_path != artifact_relative(results[0].id, ".md")
    ):
        raise HTTPException(422, error)
    try:
        verify(session, inputs, read_bytes=True)
        read_owned_file(results[0].relative_path, results[0].size_bytes, results[0].sha256, limit=1024 * 1024)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, error) from exc
    return ids, {
        "artifact_id": ids[0],
        "artifact_ids": ids,
        "message_id": messages[0].id,
        "run_id": child.id,
        "source_kind": "inspected_input",
    }
