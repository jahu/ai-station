"""Artifact registration, hashing, and thumbnails."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.events import append_event
from app.models import Artifact
from app.paths import artifact_relative, safe_join, validate_relative


def register_file(
    session: Session,
    *,
    source: Path,
    artifact_type: str,
    mime_type: str,
    original_filename: str,
    run_id: str | None,
    metadata: dict | None = None,
    parent_artifact_ids: list[str] | None = None,
    artifact_id: str | None = None,
) -> Artifact:
    settings = get_settings()
    artifact = Artifact(
        id=artifact_id,
        artifact_type=artifact_type,
        mime_type=mime_type,
        relative_path="",
        original_filename=original_filename,
        run_id=run_id,
        metadata_json=metadata or {},
        parent_artifact_ids=parent_artifact_ids or [],
    )
    session.add(artifact)
    session.flush()
    suffix = source.suffix or ".bin"
    relative = artifact_relative(artifact.id, suffix)
    destination = safe_join(settings.data_dir, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        destination.write_bytes(source.read_bytes())
    data = destination.read_bytes()
    artifact.relative_path = relative
    artifact.size_bytes = len(data)
    artifact.sha256 = hashlib.sha256(data).hexdigest()
    if artifact_type == "image":
        artifact.metadata_json = {**artifact.metadata_json, **_dimensions(destination)}
        artifact.thumbnail_relative_path = _thumbnail(settings.data_dir, artifact.id, destination)
    session.flush()
    if run_id:
        append_event(
            session,
            run_id,
            "artifact.created",
            {"artifact_id": artifact.id, "type": artifact_type, "path": relative},
        )
    return artifact


def adopt_existing(
    session: Session,
    *,
    relative_path: str,
    artifact_type: str,
    mime_type: str,
    original_filename: str,
    run_id: str | None,
    metadata: dict | None = None,
    parent_artifact_ids: list[str] | None = None,
) -> Artifact:
    settings = get_settings()
    relative = validate_relative(relative_path)
    path = safe_join(settings.data_dir, relative)
    if not path.is_file():
        raise FileNotFoundError(relative)
    data = path.read_bytes()
    artifact = Artifact(
        artifact_type=artifact_type,
        mime_type=mime_type,
        relative_path=relative,
        original_filename=original_filename,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        run_id=run_id,
        metadata_json=metadata or {},
        parent_artifact_ids=parent_artifact_ids or [],
    )
    session.add(artifact)
    session.flush()
    if artifact_type == "image":
        artifact.metadata_json = {**artifact.metadata_json, **_dimensions(path)}
        artifact.thumbnail_relative_path = _thumbnail(settings.data_dir, artifact.id, path)
    if run_id:
        append_event(
            session,
            run_id,
            "artifact.created",
            {"artifact_id": artifact.id, "type": artifact_type, "path": relative},
        )
    session.flush()
    return artifact


def _dimensions(source: Path) -> dict:
    from PIL import Image

    with Image.open(source) as image:
        if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 64 * 1024 * 1024:
            raise ValueError("Unsupported image output")
        return {"width": image.width, "height": image.height}


def _thumbnail(root: Path, artifact_id: str, source: Path) -> str:
    try:
        from PIL import Image
    except ImportError:
        return ""
    relative = f"thumbnails/{artifact_id}.jpg"
    target = safe_join(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = image.convert("RGB")
        image.thumbnail((480, 480))
        image.save(target, format="JPEG", quality=82)
    return relative
