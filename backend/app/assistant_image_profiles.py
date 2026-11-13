"""Frozen image choices and compatible rendering settings for conversation tools."""

import hashlib
import json

from fastapi import HTTPException

from app.image_control_contract import CONTROL_FIELDS, CURRENT_IMAGE_POLICIES, validate_controls
from app.image_models import choice, defaults, frozen_model
from app.models import Artifact, ModelDefinition, Run

PROFILE_FIELDS = {
    "backend",
    "model_id",
    "width",
    "height",
    "steps",
    "cfg",
    "seed",
    "max_side",
    "reference_strength",
    "reference_layout",
    "grounding_px",
}


def identity(session, identifier, mode):
    _, frozen = frozen_model(session, identifier, mode)
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inventory(session):
    from sqlalchemy import select

    identifiers = ["qwen", "juggernaut", "realesrgan"] + list(
        session.scalars(
            select(ModelDefinition.id)
            .where(ModelDefinition.category == "image", ModelDefinition.status == "registered")
            .order_by(ModelDefinition.name)
            .limit(29)
        )
    )
    models = {}
    for identifier in identifiers:
        try:
            item = choice(session, identifier)
            fingerprint = identity(session, identifier, item["modes"][0]) if item["available"] else None
        except HTTPException:
            continue
        if item["available"]:
            models[identifier] = {
                key: item[key]
                for key in (
                    "id",
                    "name",
                    "backend",
                    "modes",
                    "definition_id",
                    "maximum_references",
                    "presets",
                )
                if key in item
            }
            models[identifier]["identity"] = fingerprint
            if item["backend"] == "qwen":
                models[identifier]["edit_capabilities"] = {
                    "conditioning": "instruction-native",
                    "preferred_for": "Requested structural changes, new geometry/framing/visible extent, and arbitrary multi-reference instructions.",
                }
            elif item["backend"] == "krea2":
                models[identifier]["edit_capabilities"] = {
                    "conditioning": "reference-conditioned identity/general-edit LoRAs",
                    "preferred_for": "Appearance, style and identity-focused variations where retaining source geometry/framing is acceptable.",
                    "caution": "Can retain source framing despite a different-composition instruction; not the preferred automatic choice for structural reconstruction or expanding visible extent. Two-reference training uses scene plus identity, not arbitrary independent views.",
                }
    return {"models": models, "defaults": defaults(session)}


def source_profile(session, artifact_ids):
    if not artifact_ids:
        return {}
    seen = set()
    aid = artifact_ids[0]
    for _ in range(8):
        if aid in seen:
            return {}
        seen.add(aid)
        artifact = session.get(Artifact, aid)
        source = session.get(Run, artifact.run_id) if artifact and artifact.run_id else None
        if (
            source is None
            or artifact.owner_id != source.owner_id
            or source.status != "succeeded"
            or source.executor_type != "photo_pipe"
        ):
            return {}
        if source.parameters.get("mode") != "upscale":
            break
        parents = source.parameters.get("parent_artifact_ids", [])
        if not parents:
            return {}
        aid = parents[0]
    else:
        return {}
    return {
        **{key: value for key, value in source.parameters.items() if key in PROFILE_FIELDS},
        "source_mode": source.parameters.get("mode"),
    }


def request_profile(session, root, args, mode, artifact_ids, *, inherit_source=False):
    catalog = root.parameters.get("controller_image_catalog")
    controls = {
        key: getattr(args, key, None) for key in CONTROL_FIELDS if getattr(args, key, None) is not None
    }
    if not catalog:
        if controls:
            raise ValueError("Reference controls require a current frozen image model catalog")
        return {}
    verified = bool(
        root.parameters.get("controller_verified_edits")
        and mode in {"img2img", "recompose"}
        and not inherit_source
    )
    default_mode = "img2img" if verified else mode
    inherited = source_profile(session, artifact_ids)
    selected = getattr(args, "image_model", None)
    if selected is None and (
        inherit_source or root.parameters.get("controller_image_policy") not in CURRENT_IMAGE_POLICIES
    ):
        proposed = inherited.get("model_id") or inherited.get("backend")
        if proposed and proposed not in catalog["models"]:
            raise ValueError(
                "The source image model is unavailable; choose a compatible installed image_model"
            )
        selected = (
            proposed
            if proposed in catalog["models"] and mode in catalog["models"][proposed]["modes"]
            else catalog["defaults"]["choices"][mode]
        )
    if selected is None:
        selected = catalog["defaults"]["choices"][default_mode]
    item = catalog["models"].get(selected)
    if item is None or mode not in item["modes"]:
        raise ValueError("Choose an available compatible image_model alias from image_models")
    validate_controls(
        item["backend"],
        mode,
        controls,
        required=root.parameters.get("controller_image_policy") in CURRENT_IMAGE_POLICIES
        and not inherit_source
        and not verified,
    )
    if len(artifact_ids) > item["maximum_references"]:
        raise ValueError(
            "The selected image model does not support this many references; choose a compatible image_model"
        )
    try:
        current = choice(session, selected)
        fingerprint = identity(session, selected, mode) if current["available"] else None
    except HTTPException as exc:
        raise ValueError("The selected image model became unavailable; review the model choice") from exc
    if (not current["available"] or fingerprint != item["identity"]) or any(
        current.get(key) != item.get(key)
        for key in ("backend", "definition_id", "modes", "presets", "maximum_references")
    ):
        raise ValueError("The selected image model changed or became unavailable; review the model choice")
    values = {"backend": item["backend"]}
    values.update(item.get("presets", {}).get(mode, {}))
    if item.get("definition_id"):
        values["model_id"] = item["definition_id"]
    if (
        inherited.get("source_mode") == mode
        and inherited.get("backend") == item["backend"]
        and inherited.get("model_id") == values.get("model_id")
    ):
        values.update(
            {key: value for key, value in inherited.items() if key in PROFILE_FIELDS and key != "seed"}
        )
    if verified:
        for key in ("width", "height", "reference_layout"):
            values.pop(key, None)
    if controls:
        values.update(controls)
    return values
