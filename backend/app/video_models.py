"""Explicit installed video choices over shared definitions and native readiness."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import ModelDefinition, ModelFile
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable

router = APIRouter(prefix="/api/video/models", tags=["video"])
DB = Annotated[Session, Depends(session_scope)]


def frozen_model(session, identity, *, recheck=False):
    definition = session.get(ModelDefinition, str(identity))
    file = session.get(ModelFile, definition.file_id) if definition and definition.file_id else None
    video = definition.metadata_json.get("video") if definition else None
    binding = video.get("binding") if isinstance(video, dict) else None
    if (
        definition is None
        or definition.category != "video"
        or (definition.status != "registered" and not recheck)
        or file is None
        or file.availability != "present"
        or not binding
        or file.sha256 != video.get("sha256")
        or not file.sha256
        or file.relative_path != "models/store/" + file.sha256
        or binding.get("checkpoint_profile") != "wan22-5b-diffusion-v1"
        or binding.get("cpu_offload") is not True
        or binding.get("workload_accepted") is not True
    ):
        raise HTTPException(409, "Selected video model is unavailable or needs its reviewed workload")
    return {
        "definition_id": definition.id,
        "name": definition.name,
        "binding": dict(binding),
        "checkpoint": {
            "profile": binding["checkpoint_profile"],
            "relative_path": file.relative_path,
            "sha256": file.sha256,
            "size_bytes": file.size_bytes,
            "mtime": file.mtime,
            "schema_sha256": binding["schema_sha256"],
        },
    }


def same_model(first, second):
    return (
        isinstance(first, dict)
        and isinstance(second, dict)
        and {k: v for k, v in first.items() if k != "name"}
        == {k: v for k, v in second.items() if k != "name"}
    )


def profile_for(session, identity, observed=None, *, recheck=False):
    if identity is None:
        from app.video import capabilities

        return observed if observed is not None else capabilities()
    model = frozen_model(session, identity, recheck=recheck)
    if observed is not None and same_model(observed.get("video_model"), model):
        return observed
    try:
        report = RunnerClient(timeout=20).request(
            "POST",
            "/v1/video/model-capabilities",
            {
                "checkpoint": model["checkpoint"],
                "managed_runtime": model["binding"]["managed_runtime"],
                "permissions": ["filesystem_read"],
            },
        )
    except (RunnerError, RunnerUnavailable):
        raise HTTPException(409, "Connect the Host Runner to inspect the selected video model") from None
    if not report.get("available") or report.get("managed_runtime") != model["binding"]["managed_runtime"]:
        raise HTTPException(
            409, report.get("reason") or "The selected video model's fixed engine is unavailable"
        )
    return {**report, "video_model": model, "recommended_memory_profile": "bounded_11g"}


@router.get("")
def choices(session: DB):
    items = []
    for row in session.scalars(
        select(ModelDefinition).where(ModelDefinition.category == "video").order_by(ModelDefinition.name)
    ):
        if not isinstance(row.metadata_json.get("video"), dict):
            continue
        try:
            frozen_model(session, row.id)
            available = True
        except HTTPException:
            available = False
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "available": available,
                "cpu_offload": True,
                "profile": "1280×704 · 12 GiB GPU · 24 GiB RAM",
            }
        )
    return {"items": items}


@router.get("/{identity}/capabilities")
def selected_capabilities(identity: UUID, session: DB):
    return profile_for(session, identity)
