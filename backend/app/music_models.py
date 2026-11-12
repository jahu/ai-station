"""Explicit installed music choices over shared definitions and native readiness."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import ModelDefinition, ModelFile
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runtime_readiness import reject_checking

router = APIRouter(prefix="/api/audio/music/models", tags=["music"])
DB = Annotated[Session, Depends(session_scope, scope="function")]


def frozen_model(session, identity, *, recheck=False):
    definition = session.get(ModelDefinition, str(identity))
    file = session.get(ModelFile, definition.file_id) if definition and definition.file_id else None
    music = definition.metadata_json.get("music") if definition else None
    binding = music.get("binding") if isinstance(music, dict) else None
    if (
        definition is None
        or definition.category != "audio"
        or (definition.status != "registered" and not recheck)
        or file is None
        or file.availability != "present"
        or not binding
        or file.sha256 != music.get("sha256")
        or not file.sha256
        or file.relative_path != "models/store/" + file.sha256
        or binding.get("checkpoint_profile") != "ace-step15-turbo-diffusion-v1"
        or binding.get("cpu_offload") is not True
    ):
        raise HTTPException(409, "Selected music model is unavailable or needs its reviewed workload")
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
        return (
            observed
            if observed is not None
            else RunnerClient(timeout=20).request("GET", "/v1/music/capabilities")
        )
    model = frozen_model(session, identity, recheck=recheck)
    if observed is not None:
        if same_model(observed.get("music_model"), model):
            return observed
        raise HTTPException(409, "The selected music model changed before publication")
    try:
        report = RunnerClient(timeout=20).request(
            "POST",
            "/v1/music/model-capabilities",
            {
                "checkpoint": model["checkpoint"],
                "managed_runtime": model["binding"]["managed_runtime"],
                "permissions": ["filesystem_read"],
            },
        )
    except RunnerUnavailable:
        raise HTTPException(409, "Connect the Host Runner to inspect the selected music model") from None
    except RunnerError as exc:
        raise HTTPException(409, exc.detail) from None
    reject_checking(report, "audio.music")
    if not report.get("available") or report.get("managed_runtime") != model["binding"]["managed_runtime"]:
        raise HTTPException(
            409, report.get("reason") or "The selected music model's fixed engine is unavailable"
        )
    return {**report, "music_model": model, "music_memory_mib": 18432}


@router.get("")
def choices(session: DB):
    items = []
    for row in session.scalars(
        select(ModelDefinition).where(ModelDefinition.category == "audio").order_by(ModelDefinition.name)
    ):
        if not isinstance(row.metadata_json.get("music"), dict):
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
                "profile": "Music · 12 GiB GPU · 24 GiB RAM · CPU offload",
            }
        )
    return {"items": items}


@router.get("/{identity}/capabilities")
def selected_capabilities(identity: UUID, session: DB):
    return profile_for(session, identity)
