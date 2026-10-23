"""Resolve explicit image-result references inside one conversation, before enqueue."""

import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Artifact, ChatWorkContext, Message, Run

_REFERENCE = r"(?:it|this(?: image| picture)?|the (?:last |previous )?(?:image|picture|graphic|result)|this graphic|tę grafikę|te grafike|tą grafikę|ta grafike|to|ten obraz|ten wynik|ostatni obraz|poprzedni obraz)"


def _media_web_options(body):
    """Web availability does not force research into a selected media operation."""
    if (
        not body.web_search.enabled
        or body.web_search.query.strip()
        or body.web_search.render_pages
        or any(
            getattr(body, key, None)
            for key in (
                "coding",
                "github",
                "new_project",
                "continuation",
                "commit",
                "publish",
                "load",
                "stop",
            )
        )
    ):
        return body
    from app.assistant import explicit_plan

    plan = explicit_plan(body.model_dump(mode="json", exclude={"attachments"}))
    if plan and plan.action in {
        "image.describe",
        "image.edit",
        "image.recompose",
        "image.upscale",
        "audio.speech",
        "audio.music",
        "audio.transcribe",
        "audio.analyze",
        "avatar.animate",
        "video.generate",
    }:
        return body.model_copy(update={"web_search": body.web_search.model_copy(update={"enabled": False})})
    return body


def followup_action(content):
    text = content.strip()
    if re.fullmatch(rf"(?:describe|inspect|opisz|obejrzyj)\s+{_REFERENCE}[.!]?", text, re.I):
        return "image.describe"
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
    if mode not in {"chat", "work", "orchestrator"}:
        return body, None
    body = _media_web_options(body)
    if body.action != "auto":
        return body, None
    if any(
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
            "music",
            "upscale_result",
        )
    ) or (body.web_search.enabled and (body.web_search.query.strip() or body.web_search.render_pages)):
        return body, None
    binding = session.get(ChatWorkContext, conversation.id)
    if binding and binding.task_id:
        return body, None
    action = followup_action(body.content)
    if action is None:
        return body, None
    if body.media and action != "video.generate":
        return body, None
    # "Describe it" is also an ordinary text follow-up. Only the current result
    # may make that generic phrase a pixel request, never an unrelated old image.
    generic_description = action == "image.describe" and not re.search(
        r"\b(?:image|picture|graphic|obraz|grafik)\w*", body.content, re.I
    )
    description_task = None
    if generic_description:
        recent = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.role == "assistant")
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(32)
        )
        for latest in recent:
            if latest.metadata_json.get("superseded") or latest.metadata_json.get("routing_only"):
                continue
            context = (
                session.get(Run, latest.run_id)
                if latest.run_id and not latest.metadata_json.get("partial")
                else None
            )
            description_task = context.task_id if context and context.status == "succeeded" else None
            break
        if description_task is None:
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
        if generic_description and source.task_id != description_task:
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
            if source.metadata_json.get("plan", {}).get("action") in {
                "image.generate",
                "image.edit",
                "image.recompose",
                "image.upscale",
                "image.generate_video",
            }:
                raise HTTPException(
                    422,
                    "The latest image task has no completed result. Inspect it or select an image explicitly.",
                )
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
            update={
                "action": action,
                "image_artifact_ids": [UUID(artifact.id)],
                "web_search": body.web_search.model_copy(update={"enabled": False}),
            }
        ), reference
    if generic_description:
        return body, None
    raise HTTPException(422, "There is no recent image result in this conversation. Attach an image first.")
