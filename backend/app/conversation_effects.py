"""Current-turn film sound intent and owned, visible source authority."""

import re
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import or_, select

from app.effects_schema import EffectsRequest
from app.models import Artifact, Message, Run


class EffectsScope(EffectsRequest):
    video_artifact_id: UUID | None = None
    prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    preview_mode: Literal["mix", "replace"] = "mix"
    original_gain: float = Field(default=1.0, ge=0, le=4, strict=True, allow_inf_nan=False)
    effects_gain: float = Field(default=0.65, ge=0, le=4, strict=True, allow_inf_nan=False)


_REFERENCE = re.compile(
    r"\b(?:(?:this|that|previous|last|attached|selected)\s+(?:film|video|clip)|(?:tego|ten|tym|poprzedni\w*|ostatni\w*|wybran\w*)\s+(?:film\w*|wideo|klip\w*))\b",
    re.I,
)
_REQUEST = re.compile(
    r"^(?:(?:please|prosz[eę]|teraz|now)\s+){0,3}(?:add|generate|create|make|replace|zamie[nń]|zast[aą]p|dodaj|wygeneruj|stw[oó]rz|utw[oó]rz)\b.{0,100}?\b(?:sound(?:\s+effects)?|audio|ambience|d[zź]wi[eę]k\w*|odg[łl]os\w*)",
    re.I,
)
_NOT_GENERATION = re.compile(
    r"\b(?:agent\w*|prompts?|promptu|brief\w*|instructions?|instrukcj\w*|tutorial\w*|poradnik\w*|kod\w*|code|script\w*|skrypt\w*)\b",
    re.I,
)
_BLOCKED = (
    "data",
    "coding",
    "github",
    "new_project",
    "continuation",
    "commit",
    "publish",
    "load",
    "stop",
    "media",
    "music",
    "attachments",
    "image_artifact_ids",
    "audio_artifact_id",
    "speech_text",
    "upscale_result",
)
_VIDEO_EXECUTORS = {
    "wan_video",
    "media_compose",
    "echomimic",
    "sonic_whole",
    "effects_preview",
    "timeline_render",
}


_NEW_FILM = re.compile(
    r"^(?:(?:please|prosz[eę])\s+)?(?:generate|create|make|wygeneruj|stw[oó]rz|utw[oó]rz)\b.{0,80}?\b(?:film\w*|video|wideo|clip)\b",
    re.I,
)
_NEW_SOUND = re.compile(
    r"\b(?:with\s+(?:sound|audio|sound effects)|z\s+(?:d[zź]wi[eę]kiem|odg[łl]osami))\s*:\s*(.+)$",
    re.I | re.S,
)


def new_film_requested(params):
    if params.get("action") == "video.generate":
        return params.get("effects") is not None
    if params.get("action", "auto") != "auto":
        return False
    text = params.get("content", "").strip()
    match = _NEW_FILM.match(text)
    return bool(match and not _NOT_GENERATION.search(text[: match.end()]) and _NEW_SOUND.search(text))


def visual_prompt(params):
    text = params["content"].strip()
    match = _NEW_SOUND.search(text)
    return text[: match.start()].rstrip(" ,;.") if match else text


def prepare_new_film(body):
    if any(getattr(body, k, None) for k in _BLOCKED if k not in {"media", "image_artifact_ids"}):
        raise HTTPException(
            422, "Generate a film with optional first-frame image and its own sound description."
        )
    if len(body.image_artifact_ids) > 1:
        raise HTTPException(422, "A new film accepts at most one first-frame image.")
    scope = body.effects
    if scope is None:
        scope = EffectsScope(prompt=_NEW_SOUND.search(body.content).group(1).strip())
    if scope.video_artifact_id is not None:
        raise HTTPException(
            422, "A new film supplies its generated source; remove the existing-film selection."
        )
    if not scope.prompt:
        match = _NEW_SOUND.search(body.content)
        if not match:
            raise HTTPException(422, "Describe the sound for the new film before sending.")
        scope = scope.model_copy(update={"prompt": match.group(1).strip()})
    if body.web_search.enabled and (body.web_search.query.strip() or body.web_search.render_pages):
        raise HTTPException(422, "Run explicit web research separately from film generation.")
    from app.web_search import SearchOptions

    return body.model_copy(
        update={
            "action": "video.generate",
            "effects": scope,
            "web_search": SearchOptions(enabled=False),
            "reasoning": None,
        }
    )


def requested(params):
    if new_film_requested(params):
        return False
    if params.get("action") == "audio.effects":
        return True
    if params.get("action", "auto") != "auto":
        return False
    if params.get("effects") is not None:
        return True
    text = params.get("content", "").strip()
    return bool(_REQUEST.match(text) and _REFERENCE.search(text) and not _NOT_GENERATION.search(text))


def request(params):
    scope = EffectsScope.model_validate(params.get("effects") or {})
    values = scope.model_dump(
        mode="json", exclude={"preview_mode", "original_gain", "effects_gain", "prompt"}
    )
    prompt = scope.prompt or params["content"].partition(":")[2].strip() or params["content"].strip()
    return EffectsRequest.model_validate({**values, "prompt": prompt})


def _agent_video(session, message, control):
    from app.conversation_agent_control import definition_hash, linked_run
    from app.media_results import final_media_executor
    from app.models import Agent

    linked = linked_run(session, message, control)
    error = "The referenced agent film is unfinished or unavailable. Choose a completed film explicitly."
    if linked is None:
        scope = control.parameters.get("scope") or {}
        agent = session.get(Agent, scope.get("agent_id", ""))
        if agent is None or definition_hash(agent) != scope.get("definition_hash"):
            raise HTTPException(422, error)
        if (agent.media or {}).get("kind") in {"video", "avatar", "effects"}:
            raise HTTPException(422, error)
        return None
    root = session.get(Run, linked["id"])
    media = root.parameters.get("definition", {}).get("media") or {}
    if media.get("kind") not in {"video", "avatar", "effects"}:
        return None
    producer = session.get(Run, linked.get("result_run_id", ""))
    outcome = control.metadata_json.get("agent_control_result", {}).get("outcome")
    if (
        linked.get("status") != "succeeded"
        or producer is None
        or producer.status != "succeeded"
        or producer.executor_type != final_media_executor(media)
        or producer.task_id != root.task_id
        or producer.agent_id != root.agent_id
        or root.task.agent_id != root.agent_id
        or outcome == "queued"
        and (
            root.task.metadata_json.get("conversation_control_run_id") != control.id
            or root.task.metadata_json.get("originating_conversation_id") != message.conversation_id
        )
    ):
        raise HTTPException(422, error)
    rows = list(
        session.scalars(
            select(Artifact).where(Artifact.run_id == producer.id, Artifact.artifact_type == "video").limit(3)
        )
    )
    if len(rows) != 1:
        raise HTTPException(422, error)
    return rows[0], producer, message.id


def visible_film(session, conversation):
    rows = session.execute(
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
    for message, root in rows:
        if message.metadata_json.get("superseded"):
            continue
        if root.executor_type == "agent_control":
            result = _agent_video(session, message, root)
            if result:
                return result
            continue
        action = root.metadata_json.get("plan", {}).get("action")
        if action not in {"video.generate", "image.generate_video", "avatar.animate", "audio.effects"}:
            continue
        if message.metadata_json.get("partial"):
            raise HTTPException(
                422, "The latest film result is incomplete. Choose its finished output explicitly."
            )
        plan = root.task.metadata_json.get("media_plan") or {}
        films = list(
            session.execute(
                select(Artifact, Run)
                .join(Run, Artifact.run_id == Run.id)
                .where(
                    Run.task_id == root.task_id,
                    Run.conversation_id == conversation.id,
                    Artifact.artifact_type == "video",
                    Run.executor_type.in_(_VIDEO_EXECUTORS),
                )
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
                .limit(41)
            )
        )
        expected = plan.get("final_artifact_id")
        if root.task.metadata_json.get("soundtrack_plan"):
            from app.film_sound import stages

            sound = stages(session, root.task)
            if len(sound) != 3 or sound[-1].status != "succeeded":
                raise HTTPException(
                    422, "The latest film is still receiving its sound. Choose a completed film explicitly."
                )
            films = [pair for pair in films if pair[1].id == sound[-1].id]
            if len(films) != 1:
                raise HTTPException(422, "The completed film with sound is unavailable.")
            expected = films[0][0].id
        if plan:
            if not expected:
                raise HTTPException(
                    422, "The latest complete film is not ready yet. Do not use an intermediate segment."
                )
            films = [pair for pair in films if pair[0].id == expected]
        else:
            final = [
                pair
                for pair in films
                if pair[1].executor_type
                in {"media_compose", "effects_preview", "timeline_render", "sonic_whole"}
            ]
            if final:
                films = final
        if len(films) != 1:
            raise HTTPException(
                422, "The latest film is unfinished or ambiguous. Select one completed film in Film sound."
            )
        artifact, producer = films[0]
        if (
            producer.status != "succeeded"
            or artifact.metadata_json.get("internal_media")
            or artifact.metadata_json.get("partial")
        ):
            raise HTTPException(422, "The latest film is not a completed final result.")
        return artifact, producer, message.id
    raise HTTPException(
        422, "Choose a completed film in Film sound, or refer to one generated in this conversation."
    )


def prepare_turn(session, conversation, body, mode):
    if new_film_requested(body.model_dump(mode="json")):
        return prepare_new_film(body), None
    selected = requested(body.model_dump(mode="json"))
    if body.effects is not None and not selected:
        raise HTTPException(422, "Film sound settings apply only to Add film sound.")
    if not selected:
        return body, None
    if mode not in {"chat", "work", "orchestrator"}:
        raise HTTPException(422, "Film sound requires a conversation.")
    if any(getattr(body, k, None) for k in _BLOCKED):
        raise HTTPException(
            422, "Film sound uses one reviewed film without other action settings or attachments."
        )
    if body.web_search.enabled and (body.web_search.query.strip() or body.web_search.render_pages):
        raise HTTPException(422, "Run explicit web research separately from film sound.")
    scope = body.effects or EffectsScope(
        preview_mode="replace"
        if re.match(
            r"^(?:(?:please|prosz[eę])\s+)?(?:replace|zamie[nń]|zast[aą]p)\b", body.content.strip(), re.I
        )
        else "mix"
    )
    source_message = None
    if scope.video_artifact_id is None:
        if not _REFERENCE.search(body.content):
            raise HTTPException(422, "Select a film in Film sound before sending.")
        artifact, producer, source_message = visible_film(session, conversation)
        scope = scope.model_copy(update={"video_artifact_id": UUID(artifact.id)})
    else:
        artifact = session.get(Artifact, str(scope.video_artifact_id))
        producer = session.get(Run, artifact.run_id) if artifact else None
    from app.effects import video_snapshot

    try:
        source = video_snapshot(session, scope.video_artifact_id)
        if body.media_translation is not None:
            if scope.translation is not None and scope.translation != body.media_translation:
                raise ValueError("Choose one prompt preparation policy for this turn")
            scope = scope.model_copy(update={"translation": body.media_translation})
        parsed = request({**body.model_dump(mode="json"), "effects": scope.model_dump(mode="json")})
        if any(c.end_frame > source["frames"] for c in parsed.cues):
            raise ValueError("A sound cue exceeds the selected film")
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    reference = {
        "source_kind": "film_sound",
        "artifact_id": str(scope.video_artifact_id),
        "source_run_id": producer.id,
        "video": source,
        **({"source_message_id": source_message} if source_message else {}),
    }
    from app.web_search import SearchOptions

    return body.model_copy(
        update={
            "action": "audio.effects",
            "effects": scope,
            "web_search": SearchOptions(enabled=False),
            "reasoning": None,
        }
    ), reference


def freeze_source(session, body):
    from app.effects import video_snapshot

    return video_snapshot(session, request(body.model_dump(mode="json")).video_artifact_id)


def preflight(session, run, loader):
    """Wait only for an active bounded readiness check, outside publication."""
    import time

    deadline = time.monotonic() + 15
    while True:
        value = loader()
        if value.get("available") or value.get("readiness") != "checking" or time.monotonic() >= deadline:
            return value
        session.refresh(run)
        if run.status == "cancel_requested":
            return {"available": False, "readiness": "canceled"}
        session.commit()
        time.sleep(0.25)
