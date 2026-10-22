"""Bind an explicit screenshot inspection to its saved anonymous page evidence."""

import hashlib

from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models import Artifact, Message, Run
from app.paths import safe_join
from app.providers import ProviderError


def scope_for_images(session, parent, ids):
    """A selected image can inherit page text only from this conversation's successful capture."""
    if len(ids) != 1:
        return None
    image = session.get(Artifact, ids[0])
    browser = session.get(Run, image.run_id) if image and image.run_id else None
    if (
        image is None
        or image.metadata_json.get("tool") != "browser"
        or browser is None
        or browser.executor_type != "browser"
        or browser.status != "succeeded"
        or browser.conversation_id != parent.conversation_id
        or not browser.parent_run_id
    ):
        return None
    original = session.scalar(
        select(Message).where(
            Message.run_id == browser.parent_run_id,
            Message.role == "assistant",
            Message.conversation_id == parent.conversation_id,
        )
    )
    source = original.metadata_json.get("page_read") if original else None
    if (
        not isinstance(source, dict)
        or original.metadata_json.get("partial")
        or original.metadata_json.get("superseded")
    ):
        return None
    artifact = session.get(Artifact, source.get("artifact_id"))
    if artifact is None or not artifact.sha256:
        raise HTTPException(409, "The page capture is unavailable; read the page again")
    scope = {
        "artifact_id": artifact.id,
        "sha256": artifact.sha256,
        "source_message_id": original.id,
        "origin_message_id": original.id,
        "renderer": "browser",
        "selected_screenshot_id": image.id,
    }
    from app.chat_pages import _reused_result

    try:
        select_screenshot(_reused_result(session, parent, scope), image.id)
    except (ProviderError, ValueError) as exc:
        raise HTTPException(409, "The page capture changed or is unavailable; read the page again") from exc
    return scope


def select_screenshot(result, image_id):
    pages = [page for page in result.get("pages", []) if page.get("screenshot_artifact_id") == image_id]
    if len(pages) != 1:
        raise ProviderError("The selected screenshot does not belong to this page capture")
    return {**result, "pages": pages, "urls": [pages[0]["url"]], "selected_screenshot_id": image_id}


def frozen_visual_scope(evidence):
    visual = evidence.get("visual_analysis")
    return (
        {"message_id": visual["message_id"], "artifact_id": visual["artifact_id"], "sha256": visual["sha256"]}
        if isinstance(visual, dict)
        and all(visual.get(key) for key in ("message_id", "artifact_id", "sha256"))
        else None
    )


def visual_observation(session, run, scope, page):
    frozen = scope["visual_analysis"]
    message = session.get(Message, frozen.get("message_id"))
    vision = session.get(Run, message.run_id) if message and message.run_id else None
    artifact = session.get(Artifact, frozen.get("artifact_id"))
    selected = scope.get("selected_screenshot_id")
    binding = vision.parameters.get("page_read", {}) if vision else {}
    saved = (message.metadata_json.get("page_read") or {}).get("visual_analysis", {}) if message else {}
    if (
        message is None
        or message.role != "assistant"
        or message.conversation_id != run.conversation_id
        or message.metadata_json.get("partial")
        or message.metadata_json.get("superseded")
        or vision is None
        or vision.status != "succeeded"
        or vision.capability != "chat.vision"
        or vision.executor_type != "chat"
        or vision.conversation_id != run.conversation_id
        or vision.parameters.get("location") != "local"
        or not vision.parameters.get("model", "").startswith("llamacpp:")
        or not selected
        or vision.parameters.get("vision_artifact_ids") != [selected]
        or binding.get("artifact_id") != scope.get("artifact_id")
        or binding.get("sha256") != scope.get("sha256")
        or binding.get("origin_message_id") != page.get("origin_message_id")
        or binding.get("selected_screenshot_id") != selected
        or saved.get("artifact_id") != frozen.get("artifact_id")
        or saved.get("sha256") != frozen.get("sha256")
        or artifact is None
        or artifact.run_id != vision.id
        or artifact.artifact_type != "markdown"
        or artifact.metadata_json.get("operation") != "image.describe"
        or artifact.metadata_json.get("location") != "local"
        or artifact.metadata_json.get("model") != vision.parameters.get("model")
        or artifact.metadata_json.get("model_name") != vision.parameters.get("vision_model_name")
        or artifact.sha256 != frozen.get("sha256")
        or set(artifact.parent_artifact_ids) != {selected, scope["artifact_id"]}
    ):
        raise ProviderError("The saved visual analysis is unavailable; inspect the screenshot again")
    path = safe_join(get_settings().data_dir, artifact.relative_path)
    if not path.is_file() or path.stat().st_size > 1_024_000:
        raise ProviderError("The saved visual analysis is unavailable")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != frozen["sha256"]:
        raise ProviderError("The saved visual analysis changed; inspect the screenshot again")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderError("The saved visual analysis is unreadable") from exc
    if text != message.content:
        raise ProviderError("The saved visual analysis does not match its completed answer")
    return analysis_metadata(vision, message, artifact, text)


def analysis_metadata(run, message, artifact, text):
    return {
        "message_id": message.id,
        "run_id": run.id,
        "artifact_id": artifact.id,
        "sha256": artifact.sha256,
        "model": run.parameters["vision_model_name"],
        "description": text[:12000],
        "truncated": len(text) > 12000,
        "location": "local",
        "screenshot_id": run.parameters["vision_artifact_ids"][0],
    }


def remember_analysis(run, message, artifact):
    evidence = message.metadata_json.get("page_read")
    if run.parameters.get("page_read") and evidence and evidence.get("selected_screenshot_id"):
        message.metadata_json = {
            **message.metadata_json,
            "page_read": {
                **evidence,
                "visual_analysis": analysis_metadata(run, message, artifact, message.content),
            },
        }
