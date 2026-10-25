"""Portable image snapshots shared by Vision execution and inspected-input reuse."""

from pathlib import PurePosixPath

from app.models import Artifact, Run
from app.paths import artifact_relative
from app.python_execution import read_owned_file

MIMES = {"image/png", "image/jpeg", "image/webp"}
LIMIT = 20 * 1024 * 1024


def snapshot(artifact):
    return {
        "artifact_id": artifact.id,
        "relative_path": artifact.relative_path,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
    }


def freeze(session, ids):
    rows = [session.get(Artifact, str(aid)) for aid in ids]
    if any(row is None or row.artifact_type != "image" for row in rows):
        raise ValueError("Choose existing image artifacts")
    return [snapshot(row) for row in rows]


def verify(session, inputs, *, read_bytes=False):
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 4:
        raise ValueError("Missing inspected image input snapshot")
    for item in inputs:
        if not isinstance(item, dict) or not isinstance(item.get("artifact_id"), str):
            raise ValueError("Malformed inspected image input snapshot")
        row = session.get(Artifact, item["artifact_id"])
        if row is not None:
            session.refresh(row)
        if (
            row is None
            or row.artifact_type != "image"
            or row.trashed_at is not None
            or row.mime_type not in MIMES
            or snapshot(row) != item
        ):
            raise ValueError("An inspected image is unavailable or changed")
        if read_bytes:
            suffix = PurePosixPath(row.relative_path).suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"} or not owned_image_path(session, row, suffix):
                raise ValueError("An inspected image has an unexpected storage path")
            if not row.sha256:
                raise ValueError("Reattach this image to establish its source hash")
            read_owned_file(row.relative_path, row.size_bytes, row.sha256, limit=LIMIT)


def inspected_selection(session, parent, *, read_bytes=True):
    """Only reference resolution can pin an implicitly selected input for media."""
    from app.models import Message

    if parent is None:
        return None
    user = session.get(Message, parent.parameters.get("user_message_id", ""))
    if user is None or user.metadata_json.get("conversation_reference", {}).get("source_kind") not in {
        "inspected_input",
        "agent_image_result",
    }:
        return None
    inputs = parent.parameters.get("image_inputs")
    verify(session, inputs, read_bytes=read_bytes)
    if [item["artifact_id"] for item in inputs] != parent.parameters.get("image_artifact_ids"):
        raise ValueError("The selected image differs from its frozen input")
    return inputs


def pin_media_inputs(session, parent_run_id, parameters):
    from app.models import Run

    inputs = (
        inspected_selection(session, session.get(Run, parent_run_id), read_bytes=False)
        if parent_run_id
        else None
    )
    if inputs is not None:
        if [item["artifact_id"] for item in inputs] != parameters.get("parent_artifact_ids"):
            raise ValueError("Media sources differ from the inspected input selection")
        parameters["inspected_image_inputs"] = inputs


def verify_media_inputs(session, run):
    if "inspected_image_inputs" not in run.parameters:
        return
    inputs = run.parameters["inspected_image_inputs"]
    verify(session, inputs, read_bytes=True)
    if [item["artifact_id"] for item in inputs] != run.parameters.get("parent_artifact_ids"):
        raise ValueError("Media sources differ from the inspected input selection")


def owned_image_path(session, artifact, suffix):
    if artifact.relative_path == artifact_relative(artifact.id, suffix):
        return True
    source = session.get(Run, artifact.run_id) if artifact.run_id else None
    return bool(
        suffix == ".png"
        and source
        and source.executor_type == "photo_pipe"
        and source.status == "succeeded"
        and source.capability in {"image.generate", "image.edit", "image.recompose", "image.upscale"}
        and source.metadata_json.get("dispatch_attempted") is True
        and source.metadata_json.get("process_confirmed_gone") is True
        and artifact.metadata_json.get("capability") == source.capability
        and artifact.relative_path == artifact_relative(source.id, suffix)
    )
