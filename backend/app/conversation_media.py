"""Resolve explicit image-result references inside one conversation, before enqueue."""

import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models import Agent, Artifact, ChatWorkContext, Message, Run

_PLURAL_REFERENCE = r"(?:these images|these pictures|both images|the reference images|te obrazy|te zdjęcia|te zdjecia|oba obrazy|obie fotografie|te fotografie)"
_REFERENCE = r"(?:it|this(?: image| picture)?|the (?:last |previous )?(?:image|picture|graphic|result)|this graphic|tę grafikę|te grafike|tą grafikę|ta grafike|to|ten obraz|ten wynik|ostatni obraz|poprzedni obraz|to zdjęcie|to zdjecie|tę fotografię)"


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
    if re.fullmatch(
        rf"(?:describe|inspect|opisz|obejrzyj)\s+(?:{_REFERENCE}|{_PLURAL_REFERENCE})[.!]?", text, re.I
    ):
        return "image.describe"
    if re.fullmatch(rf"(?:upscale|powiększ|powieksz)\s+{_REFERENCE}[.!]?", text, re.I):
        return "image.upscale"
    if re.fullmatch(
        rf"(?:animate|animuj|ożyw|ozyw)\s+{_REFERENCE}(?:\s*[:—-]\s*.+|\s+(?:into |w |na ).+)?[.!]?",
        text,
        re.I,
    ):
        return "video.generate"
    edit = r"(?:edit|modify|change|edytuj|zmień|zmien)"
    joiner = r"(?:\s*[:—-]\s*|\s+(?:to|into|na)\s+)"
    if re.fullmatch(rf"{edit}\s+{_PLURAL_REFERENCE}{joiner}\S.+", text, re.I):
        return "image.recompose"
    if re.fullmatch(rf"{edit}\s+{_REFERENCE}{joiner}\S.+", text, re.I):
        return "image.edit"
    return None


def resolve_result_reference(session, conversation, body, mode):
    """Only explicit referential commands opt into the last visible image result.

    Selection never inspects another conversation, grants external permissions,
    guesses among siblings, or overrides an explicitly selected tool/input/worktree.
    """
    if body.data is not None:
        return body, None
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
            or_(
                Message.metadata_json["orchestration"].as_boolean().is_(True),
                Message.metadata_json["agent_control"]["operation"].as_string() == "run",
            ),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(32)
    )
    for message, source in previous:
        if message.metadata_json.get("superseded"):
            continue
        if generic_description and source.task_id != description_task:
            continue
        if message.metadata_json.get("partial"):
            if source.executor_type == "agent_control":
                raise HTTPException(
                    422, "The latest agent image reference is incomplete. Select its image explicitly."
                )
            if source.parameters.get("image_artifact_ids"):
                raise HTTPException(
                    422, "The latest image input has no completed inspection. Select it explicitly."
                )
            continue
        if source.executor_type == "agent_control":
            selected = agent_image_result(session, message, source)
            if selected is None:
                continue
            artifact, producer, workflow = selected
            return body.model_copy(
                update={
                    "action": action,
                    "image_artifact_ids": [UUID(artifact.id)],
                    "web_search": body.web_search.model_copy(update={"enabled": False}),
                }
            ), {
                "artifact_id": artifact.id,
                "message_id": message.id,
                "run_id": producer.id,
                "workflow_run_id": workflow.id,
                "control_run_id": source.id,
                "source_kind": "agent_image_result",
            }
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
            from app.inspected_image_reference import inspected_inputs

            inspected = inspected_inputs(session, source, message)
            if inspected is not None:
                ids, reference = inspected
                plural = bool(re.search(_PLURAL_REFERENCE, body.content, re.I))
                if len(ids) > 1 and (not plural or action not in {"image.describe", "image.recompose"}):
                    raise HTTPException(
                        422,
                        "Several inspected images match. Select one image or explicitly refer to the group.",
                    )
                return body.model_copy(
                    update={
                        "action": action,
                        "image_artifact_ids": [UUID(aid) for aid in ids],
                        "web_search": body.web_search.model_copy(update={"enabled": False}),
                    }
                ), reference
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


def agent_image_result(session, message, control):
    from app.conversation_agent_control import definition_hash, linked_run

    error = "The latest agent image is unfinished, unavailable or ambiguous. Inspect its execution or select a completed image explicitly."
    linked = linked_run(session, message, control)
    if linked is None:
        scope = control.parameters.get("scope") or {}
        agent = session.get(Agent, scope.get("agent_id", ""))
        if agent is None or definition_hash(agent) != scope.get("definition_hash"):
            raise HTTPException(422, error)
        if (agent.media or {}).get("kind") != "image":
            return None
        raise HTTPException(422, error)
    root = session.get(Run, linked["id"])
    if (root.parameters.get("definition", {}).get("media") or {}).get("kind") != "image":
        return None
    if linked["status"] != "succeeded":
        raise HTTPException(422, error)
    producer = session.get(Run, linked.get("result_run_id", ""))
    result = control.metadata_json["agent_control_result"]
    if (
        producer is None
        or producer.status != "succeeded"
        or producer.executor_type != "photo_pipe"
        or producer.agent_id != root.agent_id
        or producer.task_id != root.task_id
        or root.task.agent_id != root.agent_id
        or result.get("outcome") == "queued"
        and (
            root.task.metadata_json.get("conversation_control_run_id") != control.id
            or root.task.metadata_json.get("originating_conversation_id") != message.conversation_id
        )
    ):
        raise HTTPException(422, error)
    images = list(
        session.scalars(
            select(Artifact)
            .where(
                Artifact.run_id == producer.id,
                Artifact.artifact_type == "image",
            )
            .limit(3)
        )
    )
    if (
        len(images) != 1
        or images[0].trashed_at
        or images[0].metadata_json.get("internal_media")
        or images[0].metadata_json.get("partial")
    ):
        raise HTTPException(422, error)
    from app.vision_inputs import freeze, verify

    try:
        verify(session, freeze(session, [UUID(images[0].id)]), read_bytes=True)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, error) from exc
    return images[0], producer, root
