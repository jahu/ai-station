"""Bounded registered video choices for conversation planning; no runtime loading."""

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.models import ModelDefinition
from app.svi_models import CHECKPOINT_PROFILE
from app.video_models import frozen_model


def identity(model):
    return hashlib.sha256(
        json.dumps(
            {key: value for key, value in model.items() if key != "name"},
            sort_keys=True,
        ).encode()
    ).hexdigest()


def inventory(session, selected=None):
    """Registry metadata only; HTTP enqueue never probes hardware or loads a model."""
    result = {}
    for row in session.scalars(
        select(ModelDefinition)
        .where(
            ModelDefinition.category == "video",
            ModelDefinition.status == "registered",
        )
        .order_by((ModelDefinition.id == str(selected)).desc(), ModelDefinition.name, ModelDefinition.id)
        .limit(16)
    ):
        try:
            model = frozen_model(session, row.id)
        except HTTPException:
            continue
        recurrent = model["binding"]["checkpoint_profile"] == CHECKPOINT_PROFILE
        result[row.id] = {
            "name": row.name[:180],
            "identity": identity(model),
            "conditioning": "original-image anchor and recurrent motion"
            if recurrent
            else "last-frame continuation",
            "image_required": recurrent,
            "preferred_for": (
                "Longer image-based continuous films where retaining the original subject and scene matters."
                if recurrent
                else "Short previews or video from text without an original image."
            ),
            "workload": "One 12-GiB GPU and 18-GiB RAM; generation can take hours."
            if recurrent
            else "Use its reviewed native workload.",
            "native_readiness": "Checked before dispatch; registry presence is not inference readiness.",
        }
    return result


def public_catalog(catalog):
    return {
        key: {name: value for name, value in item.items() if name != "identity"}
        for key, item in catalog.items()
    }


def request_scope(session, root, args, images):
    scope = dict(root.parameters["controller_request"].get("media") or {})
    if scope.get("duration_seconds") not in (None, args.duration_seconds):
        raise ValueError("Keep the user's selected video duration or clarify the conflicting request")
    chosen = getattr(args, "video_model", None)
    explicit = scope.get("model_id")
    if chosen and explicit and chosen != explicit:
        raise ValueError("Keep the user's selected video model")
    chosen = explicit or chosen
    if chosen:
        offered = root.parameters.get("controller_video_catalog", {}).get(chosen)
        if offered is None:
            raise ValueError("Choose an exact registered video_models alias")
        try:
            model = frozen_model(session, chosen)
        except HTTPException as exc:
            raise ValueError("The selected video model is unavailable or changed") from exc
        if identity(model) != offered["identity"]:
            raise ValueError("The frozen video model changed; start a new request")
        if offered["image_required"] and len(images) != 1:
            raise ValueError("The recurrent video model needs exactly one original image")
        scope["model_id"] = chosen
    selected_format = getattr(args, "video_format", None)
    if selected_format:
        if not chosen:
            raise ValueError("Choose a registered video model before selecting its format")
        recurrent = model["binding"]["checkpoint_profile"] == CHECKPOINT_PROFILE
        dimensions = (480, 832) if selected_format == "portrait" else (832, 480)
        if not recurrent:
            dimensions = (704, 1280) if selected_format == "portrait" else (1280, 704)
        if scope.get("width") is not None and (scope["width"], scope["height"]) != dimensions:
            raise ValueError("Keep the user's selected video format")
        scope.update(zip(("width", "height"), dimensions, strict=True))
    scope["duration_seconds"] = args.duration_seconds
    return scope
