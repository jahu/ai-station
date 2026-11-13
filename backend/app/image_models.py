"""Image choices and versioned defaults over the existing model registry."""

import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_access import ScopedSession
from app.db import session_scope
from app.models import ModelDefinition, ModelFile, Setting
from app.personal_settings import preference_row

router = APIRouter(prefix="/images", tags=["images"])
DB = Annotated[Session, Depends(session_scope, scope="function")]
KEY = "image_model_defaults"
MODES = ("t2i", "img2img", "recompose", "upscale")
LEGACY = {
    "qwen": {
        "name": "Qwen Image",
        "backend": "qwen",
        "modes": ["t2i", "img2img", "recompose"],
        "maximum_references": 8,
    },
    "juggernaut": {
        "name": "Juggernaut XL",
        "backend": "juggernaut",
        "modes": ["t2i"],
        "maximum_references": 0,
    },
    "realesrgan": {"name": "RealESRGAN", "backend": "qwen", "modes": ["upscale"], "maximum_references": 1},
}
DEFAULTS = {"revision": 0, "choices": {mode: "realesrgan" if mode == "upscale" else "qwen" for mode in MODES}}


def defaults(session):
    row = preference_row(session, KEY)
    if row is None and isinstance(session, ScopedSession):
        # This one machine setting contains shared model IDs, not another
        # account's preferences. Project only its closed public coordinates.
        # Use the current transaction: a second default SQLite session would
        # acquire BEGIN IMMEDIATE and contend with this request's writer.
        station = session.connection().execute(select(Setting.value).where(Setting.key == KEY)).first()
        if station is not None:
            return _defaults_value(station[0])
    if row is None:
        return {"revision": 0, "choices": dict(DEFAULTS["choices"])}
    return _defaults_value(row.value)


def _defaults_value(value):
    error = HTTPException(409, "Image defaults need a valid revision and compatible model identifiers")
    if not isinstance(value, dict):
        raise error
    revision, choices = value.get("revision"), value.get("choices")
    if (
        type(revision) is not int
        or revision < 0
        or not isinstance(choices, dict)
        or set(choices) - set(MODES)
    ):
        raise error
    normalized = {}
    for mode, identifier in choices.items():
        if not isinstance(identifier, str) or len(identifier) > 64:
            raise error
        if identifier not in LEGACY:
            try:
                identifier = str(UUID(identifier))
            except ValueError:
                raise error from None
        normalized[mode] = identifier
    return {"revision": revision, "choices": {**DEFAULTS["choices"], **normalized}}


def choice(session, identifier):
    if identifier in LEGACY:
        return {"id": identifier, "definition_id": None, "available": True, **LEGACY[identifier]}
    try:
        identifier = str(UUID(identifier))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "Choose an installed compatible image model") from exc
    row = session.get(ModelDefinition, identifier)
    file = session.get(ModelFile, row.file_id) if row and row.file_id else None
    metadata = (row.metadata_json or {}).get("image") if row else None
    if row is None or row.category != "image" or not isinstance(metadata, dict):
        raise HTTPException(422, "Image model definition is unavailable")
    backend = metadata.get("backend")
    if backend not in {"qwen", "krea2"}:
        raise HTTPException(422, "Image model has no supported adapter")
    modes = metadata.get("modes", [])
    expected = {"t2i", "img2img", "recompose"}
    if not isinstance(modes, list) or not modes or not set(modes) <= expected:
        raise HTTPException(422, "Image model capabilities are invalid")
    valid_snapshot = bool(re.fullmatch(r"[a-f0-9]{64}", metadata.get("sha256", "")))
    if backend == "krea2":
        count = metadata.get("gpu_count", 2)
        valid_snapshot = (
            valid_snapshot
            and bool(re.fullmatch(r"[a-f0-9]{64}", metadata.get("profile_sha256", "")))
            and type(count) is int
            and count in {1, 2}
        )
    available = bool(
        row.status == "registered" and file and file.availability == "present" and valid_snapshot
    )
    return {
        "id": row.id,
        "definition_id": row.id,
        "name": row.name,
        "backend": backend,
        "modes": modes,
        "available": available,
        "managed_checkpoint": bool(metadata.get("binding")),
        "maximum_references": 2 if backend == "krea2" else 8,
        "gpu_count": metadata.get("gpu_count", 2)
        if backend == "krea2"
        else (metadata.get("binding") or {}).get("gpu_count", 1),
        "presets": metadata.get("presets", {}),
        "license_url": metadata.get("license_url"),
        "file": {"filename": file.filename, "format": file.format, "size_bytes": file.size_bytes}
        if file
        else None,
    }


def frozen_model(session, identifier, mode):
    selected = choice(session, identifier)
    if mode not in selected["modes"] or not selected["available"]:
        raise HTTPException(409, "Selected image model is unavailable for this operation")
    if selected["definition_id"] is None:
        return selected, None
    row = session.get(ModelDefinition, selected["definition_id"])
    file = session.get(ModelFile, row.file_id)
    image = row.metadata_json["image"]
    if not re.fullmatch(r"[a-f0-9]{64}", image.get("sha256", "")):
        raise HTTPException(409, "Image checkpoint needs verified SHA-256 metadata")
    snapshot = {
        "definition_id": row.id,
        "name": row.name,
        "backend": selected["backend"],
        "model_file": {"path": file.host_path, "size": file.size_bytes, "sha256": image["sha256"]},
    }
    if image.get("binding"):
        binding = image["binding"]
        if (
            selected["backend"] != "qwen"
            or file.sha256 != image["sha256"]
            or file.relative_path != "models/store/" + file.sha256
            or binding.get("checkpoint_profile") != "qwen-image21-diffusion-v1"
        ):
            raise HTTPException(409, "The imported image checkpoint binding is unavailable")
        snapshot["binding"] = dict(binding)
        snapshot["model_file"] = {
            "relative_path": file.relative_path,
            "size": file.size_bytes,
            "sha256": file.sha256,
            "mtime": file.mtime,
        }
    if selected["backend"] == "krea2":
        profile = image.get("profile_sha256", "")
        count = image.get("gpu_count", 2)
        if not re.fullmatch(r"[a-f0-9]{64}", profile) or type(count) is not int or count not in {1, 2}:
            raise HTTPException(409, "Krea model needs a verified runtime profile and GPU preset")
        snapshot.update(profile_sha256=profile, gpu_count=count)
    return selected, snapshot


def resolve_request(session, body):
    """Resolve defaults before queuing; explicit legacy backend callers keep authority."""
    from app.image_schema import ImageRequest

    automatic = None
    if body.model_selection == "auto":
        automatic = recommendation(
            session,
            body.mode,
            body.edit_prompt if body.mode == "img2img" else body.prompt,
            len(body.input_artifact_ids),
        )
        if (
            body.model_selection_revision is not None
            and body.model_selection_revision != automatic["revision"]
        ):
            raise HTTPException(409, "Image defaults changed; refresh the Auto preview before queuing")
    identifier = (
        automatic["choice"]["id"]
        if automatic
        else (
            str(body.model_id)
            if body.model_id
            else "realesrgan"
            if body.mode == "upscale"
            else body.backend
            if "backend" in body._explicit_fields
            else defaults(session)["choices"][body.mode]
        )
    )
    selected, snapshot = frozen_model(session, identifier, body.mode)
    preset = selected.get("presets", {}).get(body.mode, {})
    allowed = {
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
    if not isinstance(preset, dict) or set(preset) - allowed:
        raise HTTPException(409, "Image model preset contains unsupported fields")
    explicit = {key: getattr(body, key) for key in body._explicit_fields}
    explicit.pop("model_selection", None)
    explicit.pop("model_selection_revision", None)
    values = {**preset, **explicit, "backend": selected["backend"]}
    if automatic:
        values["prompt_style"] = "instruction"
    if snapshot:
        values["model_id"] = snapshot["definition_id"]
    try:
        resolved = ImageRequest.model_validate(values)
    except ValueError as exc:
        raise HTTPException(422, "Selected image model is incompatible with these parameters") from exc
    resolved._selection = automatic
    return resolved, snapshot


def recommendation(session, mode, prompt, reference_count):
    from app.image_edit_routing import VERSION, structural_intent

    configured = defaults(session)
    reason = structural_intent(prompt)
    default_id = configured["choices"][mode]
    preferred = choice(session, default_id)
    identifier = "qwen" if reason and preferred["backend"] != "qwen" else default_id
    selected, _ = frozen_model(session, identifier, mode)
    if reference_count > selected["maximum_references"]:
        selected, _ = frozen_model(session, "qwen", mode)
        reason = "reference_capacity"
    return {
        "policy": VERSION,
        "revision": configured["revision"],
        "reason": reason or "station_default",
        "choice": selected,
    }


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["img2img", "recompose"]
    prompt: str = Field(max_length=10000)
    reference_count: int = Field(default=0, ge=0, le=8, strict=True)


@router.post("/models/recommendation")
def recommend_model(body: RecommendationRequest, session: DB):
    return recommendation(session, body.mode, body.prompt, body.reference_count)


@router.get("/models")
def image_choices(session: DB):
    items = [choice(session, identifier) for identifier in LEGACY]
    for row in session.scalars(
        select(ModelDefinition).where(ModelDefinition.category == "image").order_by(ModelDefinition.name)
    ):
        if isinstance(row.metadata_json.get("image"), dict):
            items.append(choice(session, row.id))
    return {"items": items, "defaults": defaults(session)}


class DefaultsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)
    mode: Literal["t2i", "img2img", "recompose", "upscale"]
    choice: str = Field(min_length=1, max_length=64)


@router.put("/defaults")
def change_default(body: DefaultsWrite, session: DB):
    frozen_model(session, body.choice, body.mode)
    row = preference_row(session, KEY, default=defaults(session), lock=True)
    current = defaults(session)
    if current["revision"] != body.revision:
        raise HTTPException(409, "Image defaults changed; refresh before saving")
    row.value = {
        "revision": current["revision"] + 1,
        "choices": {**current["choices"], body.mode: body.choice},
    }
    session.commit()
    return defaults(session)
