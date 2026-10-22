"""Compose explicit current-turn website design questions with existing local Vision."""

import re

from app.chat_pages import _DOMAIN, _instruction_text, _rendered_result, requested_pages
from app.models import Artifact, Run
from app.permissions import require
from app.providers import ProviderError

_DESIGN = re.compile(
    r"\b(?:image\s+prompt|design|layout|typograph\w*|colou?rs?|wygl[aą]d\w*|kolor\w*|typografi\w*|"
    r"szat\w*\s+graficzn\w*|(?:prompt|brief)\b.{0,100}\b(?:grafik\w*|image|banner|poster))\b",
    re.I,
)

_TEXT_ONLY = re.compile(
    r"\b(?:text\s+only|only\s+(?:page\s+)?text|tylko\s+(?:tre[śs][ćc]|tekst)|"
    r"without\s+(?:vision|screenshots?)|bez\s+(?:vision|zrzut\w*|analizy\s+wygl[aą]du))\b",
    re.I,
)


def requested_design_page(params):
    """Web and a single explicit visual request, never a model-selected target."""
    web = params.get("web_search") or {}
    if (
        params.get("action") not in {"auto", "chat"}
        or not web.get("enabled")
        or str(web.get("query", "")).strip()
        or any(
            params.get(key)
            for key in (
                "image_artifact_ids",
                "audio_artifact_id",
                "attachments",
                "coding",
                "continuation",
                "commit",
                "publish",
                "load",
                "stop",
                "github",
                "new_project",
                "speech_text",
                "upscale_result",
                "media",
            )
        )
    ):
        return None
    text = params.get("content", "")
    if not isinstance(text, str):
        return None
    instruction = _instruction_text(text)
    intent = _DOMAIN.sub(" ", re.sub(r"\b[a-z][a-z0-9+.-]*://[^\s]+", " ", instruction, flags=re.I))
    if _TEXT_ONLY.search(intent) or not _DESIGN.search(intent):
        return None
    try:
        pages = requested_pages("Read " + _instruction_text(text))
    except ValueError:
        return None
    return pages if len(pages) == 1 else None


def enqueue_design(session, parent, message):
    """Worker-only publication; all evidence is verified before loading a model."""
    from app.vision import enqueue_inspection

    for permission in ("browser", "network_read", "filesystem_read", "manage_models"):
        require(parent.effective_permissions, permission)
    scope = parent.parameters.get("page_read") or {}
    source = session.get(Run, scope.get("browser_run_id"))
    if (
        parent.executor_type != "orchestrator"
        or parent.status != "running"
        or message.run_id != parent.id
        or message.conversation_id != parent.conversation_id
        or message.role != "assistant"
        or not parent.parameters.get("page_design")
        or requested_design_page(parent.parameters) != scope.get("urls")
        or source is None
        or source.parent_run_id != parent.id
        or source.task_id != parent.task_id
        or source.parameters.get("urls") != scope.get("urls")
    ):
        raise ProviderError("The visual page prerequisite does not match this turn")
    artifact = session.get(Artifact, source.metadata_json.get("browser", {}).get("artifact_id"))
    result = _rendered_result(session, parent, source, artifact)
    if len(result["pages"]) != 1 or not (
        200 <= result["pages"][0].get("status", 0) < 300 and result["pages"][0]["text"].strip()
    ):
        raise ProviderError("The requested page returned no readable public content")
    image = result["pages"][0]["screenshot_artifact_id"]
    binding = {
        "artifact_id": artifact.id,
        "sha256": artifact.sha256,
        "source_message_id": message.id,
        "origin_message_id": message.id,
        "renderer": "browser",
        "selected_screenshot_id": image,
    }
    # A rejection rolls back both source publication and model preparation.
    with session.begin_nested():
        parent.parameters = {**parent.parameters, "image_artifact_ids": [image]}
        child = enqueue_inspection(session, parent, page_scope=binding)
        message.metadata_json = {
            **message.metadata_json,
            "routing_only": True,
            "page_read": {
                **result,
                "origin_message_id": message.id,
                "selected_screenshot_id": image,
            },
        }
    return child
