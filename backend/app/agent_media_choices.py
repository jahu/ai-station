"""Bounded registered media choices for disabled drafts, never launch authority."""

from fastapi import HTTPException
from sqlalchemy import select

from app.models import ModelDefinition

LIMIT = 16


def catalog(session, *, identifier=None):
    from app.agent_media import SPEECH_AGENTS_ENABLED
    from app.audio_models import frozen_model as speech_model
    from app.image_models import choice
    from app.video_models import frozen_model

    result = []
    for kind, category in (("image", "image"), ("video", "video"), ("speech", "audio")):
        if kind == "speech" and not SPEECH_AGENTS_ENABLED:
            continue
        query = select(ModelDefinition).where(
            ModelDefinition.category == category, ModelDefinition.status == "registered"
        )
        if identifier is not None:
            query = query.where(ModelDefinition.id == identifier)
        rows = session.scalars(query.order_by(ModelDefinition.name, ModelDefinition.id).limit(LIMIT))
        for row in rows:
            try:
                if kind == "image":
                    selected = choice(session, row.id)
                    if not selected["available"] or "t2i" not in selected["modes"]:
                        continue
                    item = {"backend": selected["backend"], "mode": "t2i"}
                elif kind == "speech":
                    speech_model(session, row.id)
                    item = {
                        "engine": None,
                        "language": "pl",
                        "reference_required": True,
                        "cpu_offload": False,
                        "minimum_vram_mib": 6144,
                        "minimum_physical_ram_mib": 16384,
                    }
                else:
                    frozen_model(session, row.id)
                    item = {
                        "width": 1280,
                        "height": 704,
                        "minimum_steps": 20,
                        "memory_profile": "bounded_11g",
                        "cpu_offload": True,
                        "minimum_vram_mib": 12288,
                        "minimum_physical_ram_mib": 24576,
                    }
            except HTTPException:
                continue
            result.append({"kind": kind, "model_id": row.id, "name": row.name[:180], **item})
    return result


def validate_selection(session, media, offered):
    if media is None or media.kind not in {"image", "video", "speech"} or media.request.model_id is None:
        return
    identifier = str(media.request.model_id)
    matches = [item for item in offered if item["kind"] == media.kind and item["model_id"] == identifier]
    if len(matches) != 1:
        raise ValueError("Choose a model_id from registered_media_models for this output, or leave it null")
    # The prompt snapshot is not permission to resurrect a removed/unavailable choice.
    current = catalog(session, identifier=identifier)
    expected = {key: value for key, value in matches[0].items() if key != "name"}
    if not any({key: value for key, value in item.items() if key != "name"} == expected for item in current):
        raise ValueError("The registered media choice changed; leave model_id null for operator review")
    if media.kind == "image" and media.request.backend != matches[0]["backend"]:
        raise ValueError("Keep the selected image model's registered backend")
    if media.kind == "video":
        request = media.request
        if (
            request.width != 1280
            or request.height != 704
            or request.steps < 20
            or request.memory_profile != "bounded_11g"
        ):
            raise ValueError("The selected video model requires 1280×704, at least 20 steps and bounded_11g")

    return matches[0]
