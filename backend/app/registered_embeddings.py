"""Shared encoder definitions; source/setup history and memory remain account-private."""

from fastapi import HTTPException
from sqlalchemy import select

from app.embedding_binding import Binding, objects
from app.embedding_graph import fingerprint
from app.models import ModelDefinition, ModelFile


def frozen(session, identity):
    definition = session.get(ModelDefinition, str(identity))
    metadata = (definition.metadata_json or {}).get("embedding") if definition else None
    file = session.get(ModelFile, definition.file_id) if definition and definition.file_id else None
    try:
        binding = Binding.model_validate(metadata["binding"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(409, "Selected memory encoder is unavailable or unverified") from None
    if (
        definition.status != "registered"
        or definition.category != "other"
        or file is None
        or file.availability != "present"
        or file.sha256 != binding.model.sha256
        or file.relative_path != "models/store/" + file.sha256
        or file.size_bytes != binding.model.size_bytes
        or abs(file.mtime - binding.model.mtime) > 0.001
    ):
        raise HTTPException(409, "The selected memory encoder changed; re-check it before use")
    return binding.model_dump(mode="json")


def identity(binding):
    return "e5-cpu:" + fingerprint(binding)


def choices(session):
    result = []
    for row in session.scalars(
        select(ModelDefinition).where(ModelDefinition.category == "other").order_by(ModelDefinition.name)
    ):
        if not isinstance(row.metadata_json.get("embedding"), dict):
            continue
        try:
            frozen(session, row.id)
            available = True
        except HTTPException:
            available = False
        result.append(
            {"id": row.id, "name": row.name, "available": available, "dimension": 384, "device": "CPU"}
        )
    return result


def present(root, binding):
    try:
        objects(root, binding)
    except (OSError, ValueError):
        return False
    return True
