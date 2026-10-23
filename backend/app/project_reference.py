"""Resolve explicit current-turn project instructions without model inference."""

import re

from fastapi import HTTPException
from sqlalchemy import select

from app.assistant import CodingScope, explicit_plan
from app.models import Project

MARKER = re.compile(r"\b(?:in\s+(?:the\s+)?project|w\s+projekcie|dla\s+projektu)\s+", re.I)
CHANGE = re.compile(
    r"^(?:add|implement|fix|refactor|build|write|update|dodaj|zaimplementuj|napraw|"
    r"zrefaktoryzuj|zbuduj|napisz|zmie[nń]|popraw)\b",
    re.I,
)


def resolve_project_reference(session, body, mode):
    """Only a bare Work instruction can derive a fresh, local coding scope.

    Existing explicit scopes, attachments, deterministic actions and continuations
    keep their own contracts. Names come from this turn, never quoted tool output
    or history. The returned revision is rechecked by normal coding dispatch.
    """
    if body.data is not None:
        return body, None
    if (
        mode not in {"work", "orchestrator"}
        or body.action != "auto"
        or body.attachments
        or body.continuation
        or body.coding
        or body.new_project
        or body.commit
        or body.publish
        or body.load
        or body.stop
        or body.github
        or body.media
        or body.image_artifact_ids
        or body.audio_artifact_id
        or body.web_search.enabled
        or body.upscale_result
        or body.speech_text
        or explicit_plan(body.model_dump(mode="json", exclude={"attachments"})) is not None
    ):
        return body, None
    line = body.content.strip().splitlines()[0]
    # An explicitly requested external provider needs its normal sharing form.
    if re.search(r"\b(?:cursor|codex|claude)\b", body.content, re.I):
        return body, None
    markers = list(MARKER.finditer(line))
    if not markers or not (CHANGE.match(line) or markers[0].start() == 0):
        return body, None
    projects = list(session.scalars(select(Project)))
    matches = []
    for marker in markers:
        found = []
        tail = line[marker.end() :]
        for project in projects:
            name = re.escape(project.name)
            match = re.match(
                rf'(?:"{name}"|\'{name}\'|„{name}”|“{name}”|{name})(?=$|[,;:]|[.!?]$)', tail, re.I
            )
            if match:
                found.append((len(project.name), project, marker.end() + match.end()))
        if found:
            longest = max(item[0] for item in found)
            matches.extend((project, end) for size, project, end in found if size == longest)
    if markers[0].start() == 0:
        # A project heading alone, or a question about it, is ordinary discussion.
        if not matches or not any(CHANGE.match(line[end:].lstrip(" ,:;–—-")) for _, end in matches):
            return body, None
    if len(markers) != 1 or len(matches) > 1:
        raise HTTPException(409, "Name one unambiguous project, or choose it in Coding tools before sending.")
    if not matches:
        raise HTTPException(422, "Project name not found. Choose a registered project in Coding tools.")
    project, _ = matches[0]
    scope = CodingScope(
        project_id=project.id,
        expected_updated_at=project.updated_at,
        explore=True,
        model="auto",
    )
    return body.model_copy(update={"coding": scope}), {
        "project_id": project.id,
        "project_name": project.name,
        "expected_updated_at": project.updated_at.isoformat(),
        "source": "current_instruction",
        "model": "auto",
    }
