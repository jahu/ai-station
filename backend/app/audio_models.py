"""Explicit installed speech choices over shared definitions and native readiness."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import ModelDefinition, ModelFile
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runtime_readiness import reject_checking

router = APIRouter(prefix="/api/audio/models", tags=["speech"])
DB = Annotated[Session, Depends(session_scope, scope="function")]


def frozen_model(session, identity, *, recheck=False):
    definition = session.get(ModelDefinition, str(identity))
    file = session.get(ModelFile, definition.file_id) if definition and definition.file_id else None
    speech = definition.metadata_json.get("speech") if definition else None
    binding = speech.get("binding") if isinstance(speech, dict) else None
    if (
        definition is None
        or definition.category != "audio"
        or (definition.status != "registered" and not recheck)
        or file is None
        or file.availability != "present"
        or not binding
        or file.sha256 != speech.get("sha256")
        or not file.sha256
        or file.relative_path != "models/store/" + file.sha256
        or binding.get("checkpoint_profile") != "chatterbox-v3-t3-v1"
        or binding.get("cpu_offload") is not False
    ):
        raise HTTPException(409, "Selected speech model is unavailable or needs its reviewed workload")
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
            else RunnerClient(timeout=20).request("GET", "/v1/audio/capabilities")
        )
    model = frozen_model(session, identity, recheck=recheck)
    if observed is not None:
        if same_model(observed.get("speech_model"), model):
            return observed
        raise HTTPException(409, "The selected speech model changed before publication")
    try:
        report = RunnerClient(timeout=20).request(
            "POST",
            "/v1/audio/model-capabilities",
            {
                "checkpoint": model["checkpoint"],
                "managed_runtime": model["binding"]["managed_runtime"],
                "permissions": ["filesystem_read"],
            },
        )
    except RunnerUnavailable:
        raise HTTPException(409, "Connect the Host Runner to inspect the selected speech model") from None
    except RunnerError as exc:
        raise HTTPException(409, exc.detail) from None
    reject_checking(report, "audio.speech")
    if not report.get("available") or report.get("managed_runtime") != model["binding"]["managed_runtime"]:
        raise HTTPException(
            409, report.get("reason") or "The selected speech model's fixed engine is unavailable"
        )
    return {**report, "speech_model": model, "speech_memory_mib": 11264}


@router.get("")
def choices(session: DB):
    items = []
    for row in session.scalars(
        select(ModelDefinition).where(ModelDefinition.category == "audio").order_by(ModelDefinition.name)
    ):
        if not isinstance(row.metadata_json.get("speech"), dict):
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
                "cpu_offload": False,
                "profile": "Polish speech · 6 GiB GPU · 16 GiB RAM",
            }
        )
    return {"items": items}


@router.get("/{identity}/capabilities")
def selected_capabilities(identity: UUID, session: DB):
    return profile_for(session, identity)
