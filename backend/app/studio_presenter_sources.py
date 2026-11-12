"""Owned presenter inputs and the narrowly scoped complete internal-part boundary."""

import io

from PIL import Image, ImageOps

from app.models import Artifact, Run
from app.python_execution import read_owned_file
from app.studio_materials import source_snapshot
from app.whole_avatars import canvas


def portrait_snapshot(session, identity, *, verify=False):
    source = source_snapshot(session, identity, verify=verify, complete=True)
    item = session.get(Artifact, str(identity))
    if source["kind"] != "image" or source["size_bytes"] > 20 * 1024**2:
        raise ValueError("Choose a complete presenter image within 20 MiB")
    width, height = item.metadata_json.get("width"), item.metadata_json.get("height")
    canvas(width, height)
    if width * height > 4096**2:
        raise ValueError("Choose a presenter image within sixteen megapixels")
    return source


def normalize_portrait(source, output):
    raw = read_owned_file(
        source["relative_path"], source["size_bytes"], source["sha256"], limit=20 * 1024**2, binary=True
    )
    with Image.open(io.BytesIO(raw)) as picture:
        if picture.format not in {"PNG", "JPEG", "WEBP"} or picture.width * picture.height > 4096**2:
            raise ValueError("Choose an intact PNG, JPEG or WebP presenter portrait")
        canvas(*picture.size)
        picture.verify()
    with Image.open(io.BytesIO(raw)) as picture:
        picture = ImageOps.exif_transpose(picture)
        size = canvas(*picture.size)
        picture.convert("RGB").resize(size, Image.Resampling.LANCZOS).save(output, format="PNG")


def complete_internal_part(session, item):
    """Only a verified Sonic result in a closed Studio registry may bypass hiding."""
    from fastapi import HTTPException

    from app.studio_production import children, root_run

    if item.metadata_json.get("studio_role") != "presenter_part":
        return False
    origin = session.get(Run, item.run_id) if item.run_id else None
    if origin is None or origin.executor_type != "sonic_whole" or origin.status != "succeeded":
        return False
    try:
        root = root_run(session, origin.parameters.get("studio_production_root_id"))
        index = origin.parameters.get("studio_presenter_part")
        parts = root.metadata_json.get("production_state", {}).get("presenter_parts", [])
        portrait = root.metadata_json.get("production_state", {}).get("presenter_portrait", {})
        if type(index) is not int or not 0 <= index < len(parts):
            return False
        part = parts[index]
        return (
            item.metadata_json.get("studio_production_root_id") == root.id
            and item.metadata_json.get("studio_presenter_part") == index
            and (part.get("video") or {}).get("artifact_id") == item.id
            and origin.task_id in {task.id for task in children(session, root)}
            and [s["artifact_id"] for s in origin.parameters.get("whole_inputs", [])]
            == [portrait.get("artifact_id"), part["audio"]["artifact_id"]]
        )
    except (ValueError, KeyError, TypeError, HTTPException):
        return False
