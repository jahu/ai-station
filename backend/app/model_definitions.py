"""Curated model definitions, load presets and explicit local installation."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.events import append_event
from app.llama import LoadModel, enqueue_load, loadable_model
from app.model_sources import source_of, verify_source
from app.models import ModelDefinition, ModelFile, Run, RuntimeInstance
from app.permissions import require
from app.runner_client import RunnerClient, RunnerError
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.serialize import iso
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/models", tags=["models"])
DB = Annotated[Session, Depends(session_scope)]
_MMPROJ = re.compile(r"(^|[-_.])mmproj([-_.]|$)", re.IGNORECASE)

COMPATIBILITY = (
    {
        "format": "gguf",
        "category": "llm",
        "runtime": "llama.cpp",
        "adapter": "managed",
        "operational": True,
        "summary": (
            "Present GGUF language models can be loaded by the owned llama.cpp adapter after an "
            "explicit load Run. Registration only confirms the file and the already-installed "
            "container image; it never downloads weights or pulls images."
        ),
    },
    {
        "format": "gguf",
        "category": "image",
        "runtime": "stable-diffusion.cpp",
        "adapter": "none",
        "operational": False,
        "summary": "Image GGUFs are observed only. No managed image-GGUF runtime is enabled.",
    },
    {
        "format": "gguf",
        "category": "video",
        "runtime": None,
        "adapter": "none",
        "operational": False,
        "summary": "Video GGUFs are observed only. General video adapters remain unpublished.",
    },
    {
        "format": "gguf",
        "category": "audio",
        "runtime": None,
        "adapter": "none",
        "operational": False,
        "summary": "Audio GGUFs are observed only. Speech uses the installed Chatterbox adapter.",
    },
    {
        "format": "safetensors",
        "category": "image",
        "runtime": "photo_pipe",
        "adapter": "external",
        "operational": False,
        "summary": (
            "Image safetensors remain with the existing photo pipeline. Registration does not "
            "install, copy or load them."
        ),
    },
    {
        "format": "safetensors",
        "category": "llm",
        "runtime": None,
        "adapter": "none",
        "operational": False,
        "summary": "Safetensors language models are catalogued only. The managed runtime loads GGUF files.",
    },
)


class DefinitionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    file_id: UUID
    name: str = Field(min_length=1, max_length=200)
    gpus: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list, max_length=16)
    context_size: int = Field(default=4096, ge=512, le=262144, multiple_of=256)
    cache_type: Literal["f16", "q8_0"] = "f16"


class DefinitionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    gpus: list[Annotated[int, Field(ge=0)]] | None = Field(default=None, max_length=16)
    context_size: int | None = Field(default=None, ge=512, le=262144, multiple_of=256)
    cache_type: Literal["f16", "q8_0"] | None = None


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def compatibility_for(fmt: str, category: str, filename: str = "") -> dict:
    if filename and _MMPROJ.search(filename):
        return {
            "format": fmt,
            "category": category,
            "runtime": "llama.cpp",
            "adapter": "none",
            "operational": False,
            "summary": "mmproj files are vision companions and are not launched as standalone language models.",
        }
    for item in COMPATIBILITY:
        if item["format"] == fmt and item["category"] == category:
            return dict(item)
    return {
        "format": fmt,
        "category": category,
        "runtime": None,
        "adapter": "none",
        "operational": False,
        "summary": "This file is catalogued from discovery. No managed runtime adapter is enabled for it.",
    }


def needs_llama_image(row: ModelFile) -> bool:
    spec = compatibility_for(row.format, row.category, row.filename)
    return bool(spec["operational"] and spec["runtime"] == "llama.cpp")


def preset_of(row: ModelDefinition) -> dict:
    meta = row.metadata_json or {}
    gpus = meta.get("gpus") if isinstance(meta.get("gpus"), list) else []
    try:
        context_size = int(meta.get("context_size") or 4096)
    except (TypeError, ValueError):
        context_size = 4096
    cache_type = meta.get("cache_type") if meta.get("cache_type") in {"f16", "q8_0"} else "f16"
    return {
        "gpus": [
            int(item) for item in gpus if isinstance(item, int) and not isinstance(item, bool) and item >= 0
        ],
        "context_size": context_size,
        "cache_type": cache_type,
        **{k: meta[k] for k in ("runtime_profile", "ram_mib", "environment_id") if meta.get(k) is not None},
    }


def definition_dict(row: ModelDefinition, file: ModelFile | None = None) -> dict:
    from app.data_access import accessible_run_id

    spec = compatibility_for(file.format, file.category, file.filename) if file else None
    image = (row.metadata_json or {}).get("image")
    image_backend = image.get("backend") if isinstance(image, dict) and row.category == "image" else None
    if spec and image_backend in {"qwen", "krea2"}:
        spec = {
            **spec,
            "runtime": "ComfyUI · Krea 2" if image_backend == "krea2" else "photo_pipe",
            "adapter": "host-media",
            "operational": row.status == "registered",
            "summary": "Select this installed image checkpoint and operation settings in Images. Models load only when its Run executes.",
        }
    return {
        **({"image_backend": image_backend} if image_backend in {"qwen", "krea2"} else {}),
        "id": row.id,
        "name": row.name,
        "family": row.family,
        "category": row.category,
        "file_id": row.file_id,
        "capabilities": list(row.capabilities or []),
        "status": row.status,
        "last_verify_run_id": accessible_run_id(row, row.last_verify_run_id),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        "preset": preset_of(row),
        "compatibility": spec,
        "file": (
            None
            if file is None
            else {
                "id": file.id,
                "filename": file.filename,
                "host_path": file.host_path,
                **({"relative_path": file.relative_path} if file.relative_path else {}),
                "format": file.format,
                "category": file.category,
                "availability": file.availability,
                "size_bytes": file.size_bytes,
            }
        ),
    }


def get_definition(session: Session, definition_id: UUID) -> tuple[ModelDefinition, ModelFile | None]:
    row = session.get(ModelDefinition, str(definition_id))
    if row is None:
        raise HTTPException(404, "Model definition not found")
    file = session.get(ModelFile, row.file_id) if row.file_id else None
    return row, file


def active_install(session: Session, definition_id: str) -> Run | None:
    for run in session.scalars(
        select(Run).where(Run.executor_type == "model_install", Run.status.not_in(TERMINAL))
    ):
        if run.parameters.get("definition_id") == definition_id:
            return run
    return None


def store_preset(row: ModelDefinition, *, gpus, context_size, cache_type):
    if (row.metadata_json or {}).get("runtime_profile") and (
        gpus or context_size != 4096 or cache_type != "q8_0"
    ):
        raise HTTPException(422, "This managed CPU profile keeps its reviewed 4096-token Q8 preset")
    if len(set(gpus)) != len(gpus):
        raise HTTPException(422, "Choose distinct GPUs")
    row.metadata_json = {
        **row.metadata_json,
        "gpus": gpus,
        "context_size": context_size,
        "cache_type": cache_type,
    }


@router.get("/compatibility")
def compatibility():
    return {
        "items": [dict(item) for item in COMPATIBILITY],
        "note": (
            "Declared pairings of file format and category with a runtime family. They are not a "
            "successful load, health check or proof that weights run on this workstation."
        ),
    }


@router.get("/definitions")
def definitions(session: DB, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    statement = select(ModelDefinition).order_by(ModelDefinition.name, ModelDefinition.id)
    total = session.scalar(select(func.count()).select_from(ModelDefinition)) or 0
    rows = list(session.scalars(statement.limit(limit).offset(offset)))
    files = {}
    ids = [row.file_id for row in rows if row.file_id]
    if ids:
        files = {item.id: item for item in session.scalars(select(ModelFile).where(ModelFile.id.in_(ids)))}
    return {"items": [definition_dict(row, files.get(row.file_id)) for row in rows], "total": total}


@router.post("/definitions", status_code=201)
def create(body: DefinitionWrite, session: DB):
    file = session.get(ModelFile, str(body.file_id))
    if file is None:
        raise HTTPException(404, "Model file not found")
    if file.availability != "present":
        raise HTTPException(409, "Register a definition only for a file observed as present")
    if session.scalar(select(ModelDefinition.id).where(ModelDefinition.file_id == file.id).limit(1)):
        raise HTTPException(409, "This file already has a curated definition")
    row = ModelDefinition(
        name=body.name,
        family=file.family,
        category=file.category,
        file_id=file.id,
        capabilities=list(file.capabilities or []),
        status="unverified",
    )
    session.add(row)
    session.flush()
    store_preset(row, gpus=body.gpus, context_size=body.context_size, cache_type=body.cache_type)
    session.commit()
    return definition_dict(row, file)


@router.get("/definitions/{definition_id}")
def detail(definition_id: UUID, session: DB):
    row, file = get_definition(session, definition_id)
    return definition_dict(row, file)


@router.patch("/definitions/{definition_id}")
def edit(definition_id: UUID, body: DefinitionPatch, session: DB):
    row, file = get_definition(session, definition_id)
    if active_install(session, row.id):
        raise HTTPException(409, "Cancel or finish the installation Run before editing this definition")
    if body.name is not None:
        row.name = body.name
    preset = preset_of(row)
    store_preset(
        row,
        gpus=body.gpus if body.gpus is not None else preset["gpus"],
        context_size=body.context_size if body.context_size is not None else preset["context_size"],
        cache_type=body.cache_type if body.cache_type is not None else preset["cache_type"],
    )
    row.updated_at = utcnow()
    session.commit()
    return definition_dict(row, file)


@router.delete("/definitions/{definition_id}", status_code=204)
def remove(definition_id: UUID, session: DB):
    row, _file = get_definition(session, definition_id)
    if active_install(session, row.id):
        raise HTTPException(409, "Cancel the installation Run before removing this definition")
    session.delete(row)
    session.commit()


@router.post("/definitions/{definition_id}/install", status_code=202)
def install(definition_id: UUID, body: EmptyBody, session: DB):
    row, file = get_definition(session, definition_id)
    if file is None:
        raise HTTPException(409, "The linked model file is missing from the registry")
    if file.availability != "present":
        raise HTTPException(
            409, "Scan model folders again; this file was not present in the last complete scan"
        )
    if active_install(session, row.id):
        raise HTTPException(409, "This definition already has an active installation Run")
    from app.native_models import native

    check_image = needs_llama_image(file) and not native(row.metadata_json)
    task = create_task(
        session,
        title="Install " + row.name,
        prompt="Verify a local model file and its prepared native llama.cpp engine"
        if native(row.metadata_json)
        else "Verify a local model file and any already-installed llama.cpp image",
        capability="models.install",
    )
    run = create_run(
        session,
        task,
        run_type="runtime",
        capability="models.install",
        executor_type="model_install",
        execution_target="host",
        permissions=["filesystem_read", "manage_models"],
        retry_class="safe",
        parameters={
            "definition_id": row.id,
            "file_id": file.id,
            **verify_source(source_of(file)),
            "check_image": check_image,
            **({"context_size": preset_of(row)["context_size"]} if native(row.metadata_json) else {}),
            **{
                k: row.metadata_json[k]
                for k in ("runtime_profile", "ram_mib", "environment_id")
                if row.metadata_json.get(k) is not None
            },
        },
    )
    row.last_verify_run_id = run.id
    row.updated_at = utcnow()
    session.commit()
    return run_dict(run)


@router.post("/definitions/{definition_id}/load", status_code=202)
def load_definition(definition_id: UUID, body: EmptyBody, session: DB):
    row, file = get_definition(session, definition_id)
    if file is None or not loadable_model(file):
        raise HTTPException(422, "Choose a present language-model GGUF; mmproj files are vision companions")
    if row.status != "registered":
        raise HTTPException(409, "Install this definition locally before loading it")
    spec = compatibility_for(file.format, file.category, file.filename)
    if not spec["operational"]:
        raise HTTPException(409, spec["summary"])
    preset = preset_of(row)
    run = enqueue_load(
        LoadModel(
            model_file_id=file.id,
            **{
                k: preset[k]
                for k in ("runtime_profile", "ram_mib", "environment_id")
                if preset.get(k) is not None
            },
            gpus=preset["gpus"],
            context_size=preset["context_size"],
            cache_type=preset["cache_type"],
        ),
        session,
    )
    instance = session.get(RuntimeInstance, run.parameters["instance_id"])
    if instance is not None:
        instance.metadata_json = {**instance.metadata_json, "definition_id": row.id}
    session.commit()
    return run_dict(run)


class ModelInstallExecutor:
    name = "model_install"

    def execute(self, session, run):
        for permission in ("filesystem_read", "manage_models"):
            require(run.effective_permissions, permission)
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        row = session.get(ModelDefinition, run.parameters.get("definition_id"))
        file = session.get(ModelFile, run.parameters.get("file_id"))
        if row is None or file is None:
            mark_failed(session, run, "DefinitionMissing", "The model definition or file disappeared")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        transition(
            session, run, RunStatus.RUNNING, event_type="executor.started", payload={"mode": "metadata_only"}
        )
        session.commit()
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        from app.native_models import active_environment, native, ready, verification

        if native(run.parameters) and not run.parameters.get("environment_id"):
            environment_id = active_environment(run.parameters["runtime_profile"])
            if not environment_id:
                mark_failed(
                    session,
                    run,
                    "NativeEngineMissing",
                    "Prepare the native llama.cpp engine before checking this model",
                )
                return "done"
            run.parameters = {**run.parameters, "environment_id": environment_id}
            session.commit()
        try:
            report = RunnerClient(timeout=20).verify_model(
                {
                    "run_id": run.id,
                    "host_path": run.parameters["host_path"],
                    **(
                        {"app_owned": True, "model_sha256": run.parameters["model_sha256"]}
                        if run.parameters.get("app_owned")
                        else {}
                    ),
                    "size_bytes": run.parameters["size_bytes"],
                    "mtime": run.parameters["mtime"],
                    "check_image": bool(run.parameters.get("check_image")),
                    **(verification(run.parameters) if run.parameters.get("runtime_profile") else {}),
                    "permissions": run.effective_permissions,
                }
            )
        except RunnerError as exc:
            if exc.status_code < 500:
                row.status = "failed"
                row.updated_at = utcnow()
                mark_failed(session, run, "RunnerRejected", str(exc))
                return "done"
            raise
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="model-install.json",
                run_id=run.id,
                metadata={"metadata_only": True, "downloaded": False, "pulled": False},
            )
        ok = (
            report.get("present")
            and report.get("regular_file")
            and not report.get("symlink")
            and report.get("matches_observation")
            and not report.get("error")
        )
        if run.parameters.get("runtime_profile"):
            ok = bool(
                ok
                and report.get("cpu")
                == {
                    "runtime_profile": run.parameters["runtime_profile"],
                    "ram_mib": run.parameters["ram_mib"],
                    "context_size": run.parameters.get("context_size", 4096),
                }
            )
            if native(run.parameters):
                ok = bool(ok and ready(report, run.parameters))
        image = report.get("image")
        if run.parameters.get("check_image"):
            ok = bool(ok and isinstance(image, dict) and image.get("present"))
        append_event(
            session,
            run.id,
            "models.install",
            {
                "definition_id": row.id,
                "present": report.get("present"),
                "matches_observation": report.get("matches_observation"),
                "image_present": None if not isinstance(image, dict) else image.get("present"),
            },
        )
        if not ok:
            row.status = "failed"
            row.updated_at = utcnow()
            mark_failed(
                session, run, "ModelInstallFailed", report.get("error") or "Local model installation failed"
            )
            return "done"
        if native(run.parameters):
            row.metadata_json = {**row.metadata_json, "environment_id": run.parameters["environment_id"]}
        row.status = "registered"
        row.updated_at = utcnow()
        run.summary = (
            f"Confirmed {file.filename} is still present"
            + ("; llama.cpp image is already installed." if image else ".")
            + " No weights or images were downloaded."
        )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        return "done"
