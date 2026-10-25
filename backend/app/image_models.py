"""Image choices and versioned defaults over the existing model registry."""

import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import ModelDefinition, ModelFile, Setting

router = APIRouter(prefix="/images", tags=["images"])
DB = Annotated[Session, Depends(session_scope)]
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
    row = session.get(Setting, KEY)
    if row is None:
        return {"revision": 0, "choices": dict(DEFAULTS["choices"])}
    return {"revision": row.value["revision"], "choices": {**DEFAULTS["choices"], **row.value["choices"]}}


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
    available = bool(row.status == "registered" and file and file.availability == "present")
    return {
        "id": row.id,
        "definition_id": row.id,
        "name": row.name,
        "backend": backend,
        "modes": modes,
        "available": available,
        "maximum_references": 2 if backend == "krea2" else 8,
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

    identifier = (
        str(body.model_id)
        if body.model_id
        else "realesrgan"
        if body.mode == "upscale"
        else body.backend
        if "backend" in body._explicit_fields
        else defaults(session)["choices"][body.mode]
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
    values = {**preset, **explicit, "backend": selected["backend"]}
    if snapshot:
        values["model_id"] = snapshot["definition_id"]
    try:
        resolved = ImageRequest.model_validate(values)
    except ValueError as exc:
        raise HTTPException(422, "Selected image model is incompatible with these parameters") from exc
    return resolved, snapshot


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
    row = session.get(Setting, KEY)
    if row is None:
        try:
            with session.begin_nested():
                session.add(Setting(key=KEY, value=DEFAULTS))
                session.flush()
        except IntegrityError:
            pass
    # Acquire the same SQLite writer serialization used by other operator policy.
    session.execute(update(Setting).where(Setting.key == KEY).values(value=Setting.value))
    row = session.get(Setting, KEY, populate_existing=True)
    current = defaults(session)
    if current["revision"] != body.revision:
        raise HTTPException(409, "Image defaults changed; refresh before saving")
    row.value = {
        "revision": current["revision"] + 1,
        "choices": {**current["choices"], body.mode: body.choice},
    }
    session.commit()
    return defaults(session)
