"""Resolve explicit image-result references inside one conversation, before enqueue."""

import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Artifact, ChatWorkContext, Message, Run

_REFERENCE = r"(?:it|this(?: image| picture)?|the (?:last |previous )?(?:image|picture|result)|to|ten obraz|ten wynik|ostatni obraz|poprzedni obraz)"


def followup_action(content):
    text = content.strip()
    if re.fullmatch(rf"(?:upscale|powiększ|powieksz)\s+{_REFERENCE}[.!]?", text, re.I):
        return "image.upscale"
    if re.fullmatch(
        rf"(?:animate|animuj|ożyw|ozyw)\s+{_REFERENCE}(?:\s*[:—-]\s*.+|\s+(?:into |w |na ).+)?[.!]?",
        text,
        re.I,
    ):
        return "video.generate"
    if re.fullmatch(rf"(?:edit|modify|change|edytuj|zmień|zmien)\s+{_REFERENCE}\s*[:—-]\s*\S.+", text, re.I):
        return "image.edit"
    return None


def resolve_result_reference(session, conversation, body, mode):
    """Only explicit referential commands opt into the last visible image result.

    Selection never inspects another conversation, grants external permissions,
    guesses among siblings, or overrides an explicitly selected tool/input/worktree.
    """
    if mode not in {"chat", "work", "orchestrator"} or body.action != "auto":
        return body, None
    if (
        any(
            getattr(body, key, None)
            for key in (
                "image_artifact_ids",
                "audio_artifact_id",
                "attachments",
                "coding",
                "github",
                "new_project",
                "continuation",
                "commit",
                "publish",
                "load",
                "stop",
                "speech_text",
                "upscale_result",
            )
        )
        or body.web_search.enabled
    ):
        return body, None
    binding = session.get(ChatWorkContext, conversation.id)
    if binding and binding.task_id:
        return body, None
    action = followup_action(body.content)
    if action is None:
        return body, None
    if body.media and action != "video.generate":
        return body, None
    previous = session.execute(
        select(Message, Run)
        .join(Run, Message.run_id == Run.id)
        .where(
            Message.conversation_id == conversation.id,
            Run.conversation_id == conversation.id,
            Message.role == "assistant",
            Message.metadata_json["orchestration"].as_boolean().is_(True),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(32)
    )
    for message, source in previous:
        if message.metadata_json.get("superseded") or message.metadata_json.get("partial"):
            continue
        images = list(
            session.execute(
                select(Artifact, Run)
                .join(Run, Artifact.run_id == Run.id)
                .where(
                    Run.task_id == source.task_id,
                    Run.conversation_id == conversation.id,
                    Artifact.artifact_type == "image",
                )
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
                .limit(41)
            )
        )
        images = [(a, r) for a, r in images if not a.metadata_json.get("internal_media")]
        if not images:
            continue
        ancestors = {parent for artifact, _ in images for parent in artifact.parent_artifact_ids}
        leaves = [(a, r) for a, r in images if a.id not in ancestors]
        if len(images) > 40 or len(leaves) != 1:
            raise HTTPException(
                422, "Several image results match. Choose Use in next prompt on the intended image."
            )
        artifact, producer = leaves[0]
        if source.status != "succeeded" or producer.status != "succeeded" or artifact.trashed_at:
            raise HTTPException(
                422,
                "The latest image result is unavailable. Attach a completed image or restore it from Library.",
            )
        reference = {"artifact_id": artifact.id, "message_id": message.id, "run_id": producer.id}
        return body.model_copy(
            update={"action": action, "image_artifact_ids": [UUID(artifact.id)]}
        ), reference
    raise HTTPException(422, "There is no recent image result in this conversation. Attach an image first.")
