"""Explicit installed avatar choices over shared definitions and native readiness."""

import math
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import ModelDefinition, ModelFile
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable

router = APIRouter(prefix="/api/avatars/models", tags=["avatar"])
DB = Annotated[Session, Depends(session_scope, scope="function")]


def frozen_model(session, identity, *, recheck=False):
    definition = session.get(ModelDefinition, str(identity))
    file = session.get(ModelFile, definition.file_id) if definition and definition.file_id else None
    avatar = definition.metadata_json.get("avatar") if definition else None
    binding = avatar.get("binding") if isinstance(avatar, dict) else None
    if (
        definition is None
        or definition.category != "video"
        or (definition.status != "registered" and not recheck)
        or file is None
        or file.availability != "present"
        or not isinstance(binding, dict)
        or not {"checkpoint_profile", "schema_sha256", "module_metadata_sha256", "managed_runtime"}
        <= set(binding)
        or file.sha256 != avatar.get("sha256")
        or not file.sha256
        or file.relative_path != "models/store/" + file.sha256
        or binding.get("checkpoint_profile") != "sonic-whole-unet-v1"
        or binding.get("cpu_offload") is not True
    ):
        raise HTTPException(409, "Selected avatar model is unavailable or needs its reviewed workload")
    result = {
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
            "module_metadata_sha256": binding["module_metadata_sha256"],
        },
    }
    validate_snapshot(result)
    return result


def validate_snapshot(model):
    """Closed portable coordinates; a native query still verifies actual files."""
    try:
        checkpoint, binding = (model["checkpoint"], model["binding"])
        runtime = binding["managed_runtime"]
        if not set(model) == {"definition_id", "name", "binding", "checkpoint"}:
            raise ValueError("Invalid frozen avatar coordinate")
        if not str(UUID(model["definition_id"])) == model["definition_id"]:
            raise ValueError("Invalid frozen avatar coordinate")
        if not (isinstance(model["name"], str) and 1 <= len(model["name"]) <= 180):
            raise ValueError("Invalid frozen avatar coordinate")
        if not set(checkpoint) == {
            "profile",
            "relative_path",
            "sha256",
            "size_bytes",
            "mtime",
            "schema_sha256",
            "module_metadata_sha256",
        }:
            raise ValueError("Invalid frozen avatar coordinate")
        if not checkpoint["profile"] == binding["checkpoint_profile"] == "sonic-whole-unet-v1":
            raise ValueError("Invalid frozen avatar coordinate")
        if not checkpoint["schema_sha256"] == binding["schema_sha256"]:
            raise ValueError("Invalid frozen avatar coordinate")
        if not checkpoint["module_metadata_sha256"] == binding["module_metadata_sha256"]:
            raise ValueError("Invalid frozen avatar coordinate")
        if not all(
            (
                isinstance(checkpoint[k], str) and re.fullmatch("[a-f0-9]{64}", checkpoint[k])
                for k in ("sha256", "schema_sha256", "module_metadata_sha256")
            )
        ):
            raise ValueError("Invalid frozen avatar coordinate")
        if not checkpoint["relative_path"] == "models/store/" + checkpoint["sha256"]:
            raise ValueError("Invalid frozen avatar coordinate")
        if not (type(checkpoint["size_bytes"]) is int and 128 <= checkpoint["size_bytes"] <= 32 * 1024**3):
            raise ValueError("Invalid frozen avatar coordinate")
        if not (
            type(checkpoint["mtime"]) in {float, int}
            and math.isfinite(checkpoint["mtime"])
            and (checkpoint["mtime"] >= 0)
        ):
            raise ValueError("Invalid frozen avatar coordinate")
        if not set(runtime) == {"profile", "manifest_sha256", "environment_id"}:
            raise ValueError("Invalid frozen avatar coordinate")
        if not runtime["profile"] == "sonic-whole-linux-x86-64-python310-v1":
            raise ValueError("Invalid frozen avatar coordinate")
        if not all(
            (
                isinstance(runtime[k], str) and re.fullmatch("[a-f0-9]{64}", runtime[k])
                for k in ("manifest_sha256", "environment_id")
            )
        ):
            raise ValueError("Invalid frozen avatar coordinate")
        if not (binding["cpu_offload"] is True and binding["ram_mib"] == 18432):
            raise ValueError("Invalid frozen avatar coordinate")
        if not (binding["minimum_physical_ram_mib"] == 24576 and binding["minimum_vram_mib"] == 12288):
            raise ValueError("Invalid frozen avatar coordinate")
        if not binding["maximum_seconds"] == 60:
            raise ValueError("Invalid frozen avatar coordinate")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(409, "The frozen avatar model needs inspection; refresh Models") from exc
    return model


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
            else RunnerClient(timeout=20).request("GET", "/v1/avatar/whole-capabilities")
        )
    model = frozen_model(session, identity, recheck=recheck)
    if observed is not None:
        if same_model(observed.get("avatar_model"), model):
            return observed
        raise HTTPException(409, "The selected avatar model changed before publication")
    return profile_for_snapshot(model)


def profile_for_snapshot(model, *, allow_checking=False):
    """Inspect a frozen Run binding without replacing it with a later default."""
    validate_snapshot(model)
    try:
        report = RunnerClient(timeout=20).request(
            "POST",
            "/v1/avatar/model-capabilities",
            {
                "checkpoint": model["checkpoint"],
                "managed_runtime": model["binding"]["managed_runtime"],
                "permissions": ["filesystem_read"],
            },
        )
    except RunnerUnavailable:
        raise HTTPException(409, "Connect the Host Runner to inspect the selected avatar model") from None
    except RunnerError as exc:
        raise HTTPException(409, exc.detail) from None
    matching = (
        report.get("managed_runtime") == model["binding"]["managed_runtime"]
        and report.get("checkpoint") == model["checkpoint"]
    )
    if (
        allow_checking
        and matching
        and report.get("readiness") == "checking"
        and report.get("available") is False
    ):
        return {**report, "avatar_model": model, "avatar_memory_mib": 18432}
    if (
        not report.get("available")
        or report.get("managed_runtime") != model["binding"]["managed_runtime"]
        or report.get("checkpoint") != model["checkpoint"]
        or (report.get("recipe") or {}).get("environment_id")
        != model["binding"]["managed_runtime"]["environment_id"]
    ):
        raise HTTPException(
            409, report.get("reason") or "The selected avatar model's fixed engine is unavailable"
        )
    return {**report, "avatar_model": model, "avatar_memory_mib": 18432}


def profile_for_request(session, body, observed=None, *, frozen=None):
    identity = getattr(body, "model_id", None)
    if identity is None:
        if frozen is not None or observed is not None and observed.get("avatar_model"):
            raise HTTPException(409, "Choose the frozen avatar model explicitly")
        from app.whole_avatars import capabilities

        return observed if observed is not None else capabilities()
    if frozen is None:
        return profile_for(session, identity, observed)
    validate_snapshot(frozen)
    if frozen["definition_id"] != str(identity):
        raise HTTPException(409, "The avatar model changed during publication")
    if observed is not None:
        if not same_model(observed.get("avatar_model"), frozen):
            raise HTTPException(409, "The avatar model observation changed during publication")
        return observed
    return profile_for_snapshot(frozen)


@router.get("")
def choices(session: DB):
    items = []
    for row in session.scalars(
        select(ModelDefinition).where(ModelDefinition.category == "video").order_by(ModelDefinition.name)
    ):
        if not isinstance(row.metadata_json.get("avatar"), dict):
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
                "profile": "Avatar · 12 GiB GPU · 24 GiB RAM · CPU offload",
            }
        )
    return {"items": items}


@router.get("/{identity}/capabilities")
def selected_capabilities(identity: UUID, session: DB):
    return profile_for_snapshot(frozen_model(session, identity), allow_checking=True)
