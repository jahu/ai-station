"""Worker-owned prompt translation; media remains gated by ordinary Run prerequisites."""

import asyncio
import hashlib
import json
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.chat_providers import BUILTIN_KEY, completion_stream, ensure_builtin
from app.config import get_settings
from app.db import session_scope, utcnow
from app.dependencies import active_dependents, depend_on
from app.events import append_event
from app.local_provider import local_endpoint
from app.media_translation_text import (
    FIELD_LIMITS,
    SYSTEM,
    TranslationOptions,
    decode_fields,
    digest,
    encode_fields,
)
from app.models import Artifact, ModelDefinition, ModelFile, Run, RunDependency, RuntimeInstance, Setting
from app.paths import safe_join
from app.permissions import require
from app.runs import create_run, mark_failed, request_cancel, run_dict, transition
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/generation", tags=["generation"])
DB = Annotated[Session, Depends(session_scope)]
KEY = "media_prompt_translation"
RECEIPT = "prompt_translation"
DEFAULT = {"revision": 0, "enabled": False, "model": "", "target_language": "en"}


def preferences(session):
    row = session.get(Setting, KEY)
    return {**DEFAULT, **(row.value if row else {})}


class PreferencesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)
    enabled: StrictBool
    model: str = Field(default="", max_length=200)
    target_language: Literal["en"] = "en"


def validate_model(session, model):
    if not model.strip():
        raise HTTPException(409, "Choose a local translator in Settings → Generation")
    if model.startswith("llamacpp:"):
        from app.llama import loadable_model

        try:
            row = session.get(ModelFile, str(UUID(model.removeprefix("llamacpp:"))))
        except ValueError as exc:
            raise HTTPException(422, "Choose a present local language-model GGUF") from exc
        if not loadable_model(row):
            raise HTTPException(409, "The selected translator GGUF is unavailable")
    else:
        local_endpoint()  # Only the administrator's existing local server; never a caller URL.


def translator_label(session, model):
    if model.startswith("llamacpp:"):
        file_id = model.removeprefix("llamacpp:")
        name = session.scalar(
            select(ModelDefinition.name)
            .where(ModelDefinition.file_id == file_id, ModelDefinition.category == "llm")
            .order_by(ModelDefinition.id)
            .limit(1)
        )
        file = session.get(ModelFile, file_id)
        return name or (file.filename if file else model)
    return model


@router.get("/preferences")
def get_preferences(session: DB):
    return preferences(session)


@router.put("/preferences")
def save_preferences(body: PreferencesWrite, session: DB):
    if body.enabled:
        validate_model(session, body.model)
    if session.get(Setting, KEY) is None:
        try:
            with session.begin_nested():
                session.add(Setting(key=KEY, value=dict(DEFAULT)))
                session.flush()
        except IntegrityError:
            pass
    session.execute(update(Setting).where(Setting.key == KEY).values(value=Setting.value))
    current = session.get(Setting, KEY, populate_existing=True)
    if current.value["revision"] != body.revision:
        raise HTTPException(409, "Generation settings changed; refresh before saving")
    current.value = {**body.model_dump(), "revision": body.revision + 1}
    session.commit()
    return preferences(session)


def image_fields(run):
    params = run.parameters
    if params.get("mode") == "upscale":
        return {}
    keys = ["edit_prompt" if params.get("mode") == "img2img" else "prompt", "negative", "video_prompt"]
    return {key: params[key] for key in keys if params.get(key)}


def source_hash(run, fields):
    return digest(
        {
            "fields": fields,
            "inputs": run.parameters.get("inputs", []),
            "krea_inputs": run.parameters.get("krea_inputs", []),
            "image_model": run.parameters.get("image_model"),
            "mode": run.parameters.get("mode"),
            "gpu": run.requested_gpu,
        }
    )


def enqueue_translation(session, media, options=None, *, policy=None):
    options = TranslationOptions.model_validate(options or {})
    policy = dict(policy or preferences(session))
    enabled = policy["enabled"] if options.mode == "inherit" else options.mode == "on"
    fields = image_fields(media)
    if not enabled or not fields:
        return None
    validate_model(session, policy["model"])
    policy.setdefault("model_label", translator_label(session, policy["model"]))
    encoded, tokens = encode_fields(fields, options.protected_terms)
    provider = ensure_builtin(session)
    child = create_run(
        session,
        media.task,
        run_type="preparation",
        capability="media.prompt.translate",
        executor_type="media_translate",
        execution_target="container",
        operation_key="media-translation:" + media.id,
        parent_run_id=media.id,
        permissions=["workspace_write"],
        retry_class="inspect",
        triggered_by=media.triggered_by,
        parameters={
            "consumer_run_id": media.id,
            "policy": policy,
            "model": policy["model"],
            "provider": BUILTIN_KEY,
            "location": "local",
            "secret_ref": provider.secret_ref,
            "endpoint": local_endpoint(),
            "original": fields,
            "encoded": encoded,
            "tokens": tokens,
            "source_hash": source_hash(media, fields),
            "options": options.model_dump(),
            "temperature": 0.0,
            "system_prompt": SYSTEM,
            "max_tokens": 4096,
            "json_output": True,
            "require_complete": True,
        },
    )
    from app.llama import prepare_consumer

    prepare_consumer(session, child)
    depend_on(session, media, child)
    media.metadata_json = {
        **media.metadata_json,
        RECEIPT: {
            "preparation_run_id": child.id,
            "origin_run_id": media.id,
            "original": fields,
            "policy": policy,
            "options": options.model_dump(),
            "status": "queued",
        },
    }
    append_event(session, media.id, "media.translation.queued", {"preparation_run_id": child.id})
    return child


def consumer(session, run):
    media = session.get(Run, run.parameters.get("consumer_run_id"))
    if (
        not media
        or media.status != "queued"
        or media.task_id != run.task_id
        or media.executor_type != "photo_pipe"
    ):
        raise ValueError("Translation has no matching media request")
    receipt = media.metadata_json.get(RECEIPT, {})
    prep_id = run.id if run.executor_type == "media_translate" else run.parent_run_id
    if receipt.get("preparation_run_id") != prep_id or receipt.get("origin_run_id") != media.id:
        raise ValueError("Translation belongs to a different media request")
    if source_hash(media, run.parameters["original"]) != run.parameters["source_hash"]:
        raise ValueError("Media inputs or original instructions changed during translation")
    if image_fields(media) != run.parameters["original"]:
        raise ValueError("Media instructions changed before translation could be applied")
    return media


def stopped(session, run, *, finalize=True):
    session.refresh(run)
    media = session.get(Run, run.parameters["consumer_run_id"], populate_existing=True)
    session.refresh(run.task, ["metadata_json"])
    expired = False
    if media and media.parameters.get("execution_deadline_at"):
        expired = datetime.fromisoformat(media.parameters["execution_deadline_at"]) <= utcnow()
    canceled = (
        run.status in {"cancel_requested", "canceled"}
        or not media
        or media.status != "queued"
        or expired
        or run.task.metadata_json.get("stop_requested_at")
    )
    if canceled and finalize and run.status not in TERMINAL:
        if run.status != "cancel_requested":
            request_cancel(session, run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
    session.commit()
    return canceled


def save_receipt(session, run, media, effective, *, reviewed=False):
    prep = session.get(Run, media.metadata_json[RECEIPT]["preparation_run_id"])
    payload = {
        "version": 1,
        "origin_run_id": media.id,
        "task_id": media.task_id,
        "preparation_run_id": media.metadata_json[RECEIPT]["preparation_run_id"],
        "source_hash": run.parameters["source_hash"],
        "policy": run.parameters["policy"],
        "translator": prep.metadata_json.get("translator"),
        "original": run.parameters["original"],
        "effective": effective,
        "reviewed": reviewed,
    }
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.flush()
        artifact = register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="prompt-translation.json",
            run_id=run.id,
            metadata={"operation": "media.prompt.translate"},
            parent_artifact_ids=media.parameters.get("parent_artifact_ids", []),
        )
    return artifact


def checked_effective(original, effective):
    if set(effective) != set(original) or any(
        not isinstance(text, str)
        or not text.strip()
        or len(text) > FIELD_LIMITS.get(key, 10000)
        or "\0" in text
        for key, text in effective.items()
    ):
        raise ValueError("Reviewed translation has invalid descriptive fields")


def apply_effective(session, run, media, effective, *, reviewed=False):
    checked_effective(run.parameters["original"], effective)
    artifact = save_receipt(session, run, media, effective, reviewed=reviewed)
    media.parameters = {**media.parameters, **effective}
    media.metadata_json = {
        **media.metadata_json,
        RECEIPT: {
            **media.metadata_json[RECEIPT],
            "status": "ready",
            "effective": effective,
            "artifact_id": artifact.id,
            "artifact_sha256": artifact.sha256,
            "reviewed": reviewed,
        },
    }
    append_event(
        session, media.id, "media.translation.applied", {"artifact_id": artifact.id, "reviewed": reviewed}
    )


class MediaTranslationExecutor:
    name = "media_translate"

    def execute(self, session, run):
        require(run.effective_permissions, "workspace_write")
        if stopped(session, run):
            return "done"
        media = consumer(session, run)
        run.metadata_json = {**run.metadata_json, "translator": translator_snapshot(session, run)}
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(
            session,
            run,
            RunStatus.RUNNING,
            event_type="executor.started",
            payload={"model": run.parameters["model"], "location": "local"},
        )
        session.commit()
        try:
            result = asyncio.run(self.consume(session, run))
            if stopped(session, run):
                return "done"
            effective = decode_fields(result, run.parameters["original"], run.parameters["tokens"])
            media = consumer(session, run)
            if run.parameters["options"]["review"]:
                from app.approvals import request_run_approval

                artifact = save_receipt(session, run, media, effective)
                review = create_run(
                    session,
                    media.task,
                    run_type="preparation",
                    capability="media.prompt.review",
                    executor_type="media_translation_apply",
                    execution_target="container",
                    operation_key="translation-review:" + media.id,
                    parent_run_id=run.id,
                    permissions=["workspace_write"],
                    retry_class="inspect",
                    parameters={
                        key: run.parameters[key]
                        for key in ["consumer_run_id", "original", "source_hash", "policy"]
                    }
                    | {
                        "effective": effective,
                        "candidate_artifact_id": artifact.id,
                        "candidate_sha256": artifact.sha256,
                    },
                )
                request_run_approval(
                    session,
                    review,
                    action="media.prompt.review",
                    reason="Review the translated prompt before media generation",
                    payload={"consumer_run_id": media.id, "effective_hash": digest(effective)},
                )
                depend_on(session, media, review)
                media.metadata_json = {
                    **media.metadata_json,
                    RECEIPT: {
                        **media.metadata_json[RECEIPT],
                        "status": "waiting_for_review",
                        "effective": effective,
                        "review_run_id": review.id,
                    },
                }
            else:
                apply_effective(session, run, media, effective)
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        except Exception as exc:
            session.rollback()
            if not stopped(session, run):
                mark_failed(
                    session,
                    run,
                    "PromptTranslationFailed",
                    str(exc) or "Translation failed; retry or use the original",
                )
        return "done"

    async def consume(self, session, run):
        params = {
            **run.parameters,
            "messages": [
                {"role": "system", "content": run.parameters["system_prompt"]},
                {"role": "user", "content": json.dumps(run.parameters["encoded"], ensure_ascii=False)},
            ],
        }
        stream = completion_stream(session, params)
        text, pending = "", None
        try:
            async with asyncio.timeout(300):
                while True:
                    if stopped(session, run, finalize=False):
                        return ""
                    if pending is None:
                        pending = asyncio.create_task(anext(stream))
                    ready, _ = await asyncio.wait([pending], timeout=0.25)
                    if not ready:
                        continue
                    try:
                        token = pending.result()
                    except StopAsyncIteration:
                        return text
                    finally:
                        pending = None
                    if not isinstance(token, str) or len(text) + len(token) > 128000:
                        raise ValueError("Translation exceeded its output bound")
                    text += token
        finally:
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await pending
            await stream.aclose()


def translator_snapshot(session, run):
    snapshot = {
        "provider": BUILTIN_KEY,
        "model": run.parameters["model"],
        "endpoint": run.parameters["endpoint"],
        "system_prompt_sha256": digest(run.parameters["system_prompt"]),
    }
    if not run.parameters["model"].startswith("llamacpp:"):
        return {**snapshot, "kind": "local-server", "weights_revision": None}
    instance_id = run.parameters["endpoint"].removeprefix("llamacpp:")
    instance = session.get(RuntimeInstance, instance_id)
    if (
        not instance
        or instance.status != "ready"
        or instance.ownership != "managed"
        or instance.metadata_json.get("model_file_id") != run.parameters["model"].removeprefix("llamacpp:")
    ):
        raise ValueError("The selected translator runtime is not ready or changed identity")
    load = session.get(Run, instance.metadata_json.get("load_run_id"))
    if not load or load.status != "succeeded":
        raise ValueError("The selected translator has no verified model startup")
    return {
        **snapshot,
        "kind": "llama.cpp",
        "instance_id": instance.id,
        "load_run_id": load.id,
        "source": {
            key: load.parameters.get(key) for key in ["model_path", "size_bytes", "mtime", "projector"]
        },
        "runtime": {
            key: instance.metadata_json.get(key)
            for key in ["gpus", "context_size", "cache_type", "n_ctx_train"]
        },
    }


class TranslationApplyExecutor:
    name = "media_translation_apply"

    def execute(self, session, run):
        from app.approvals import latest_approval

        require(run.effective_permissions, "workspace_write")
        if stopped(session, run):
            return "done"
        approval = latest_approval(session, run.id)
        if (
            not approval
            or approval.resolution != "granted"
            or approval.payload.get("effective_hash") != digest(run.parameters["effective"])
        ):
            raise ValueError("Translated prompt has no matching reviewed approval")
        media = consumer(session, run)
        candidate = read_receipt(
            session, run.parameters["candidate_artifact_id"], run.parameters["candidate_sha256"]
        )
        if (
            candidate["original"] != run.parameters["original"]
            or candidate["source_hash"] != run.parameters["source_hash"]
            or candidate["preparation_run_id"] != run.parent_run_id
        ):
            raise ValueError("Reviewed translation candidate changed")
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        apply_effective(session, run, media, run.parameters["effective"], reviewed=True)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


def validate_media_translation(session, run):
    receipt = run.metadata_json.get(RECEIPT)
    if not receipt:
        return
    if receipt.get("status") == "original":
        if image_fields(run) != receipt.get("original") or receipt.get("effective") != receipt.get(
            "original"
        ):
            raise ValueError("The original prompt differs from the explicit bypass receipt")
        return
    if receipt.get("status") != "ready":
        raise ValueError("Prompt translation has not completed")
    payload = read_receipt(session, receipt.get("artifact_id"), receipt.get("artifact_sha256"))
    artifact = session.get(Artifact, receipt["artifact_id"])
    producer = session.get(Run, artifact.run_id)
    if producer and (
        (producer.executor_type == "media_translate" and producer.id != receipt.get("preparation_run_id"))
        or (
            producer.executor_type == "media_translation_apply"
            and producer.parent_run_id != receipt.get("preparation_run_id")
        )
    ):
        raise ValueError("Prompt translation producer does not match its preparation")
    if (
        not producer
        or producer.executor_type not in {"media_translate", "media_translation_apply"}
        or producer.status != "succeeded"
        or producer.task_id != run.task_id
        or payload.get("task_id") != run.task_id
        or payload.get("origin_run_id") != receipt.get("origin_run_id")
        or payload.get("preparation_run_id") != receipt.get("preparation_run_id")
        or payload.get("effective") != receipt.get("effective")
        or payload.get("original") != receipt.get("original")
        or payload.get("policy") != receipt.get("policy")
        or image_fields(run) != payload.get("effective")
        or source_hash(run, payload["original"]) != payload.get("source_hash")
    ):
        raise ValueError("Prompt translation receipt belongs to different media")


def read_receipt(session, artifact_id, expected):
    artifact = session.get(Artifact, artifact_id)
    if (
        not artifact
        or artifact.artifact_type != "json"
        or artifact.sha256 != expected
        or artifact.purged_at
        or artifact.purge_run_id
        or artifact.trashed_at
    ):
        raise ValueError("Prompt translation receipt is unavailable")
    path = safe_join(get_settings().data_dir, artifact.relative_path)
    with path.open("rb") as handle:
        content = handle.read(256001)
    if len(content) > 256000:
        raise ValueError("Prompt translation receipt exceeds its bound")
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("Prompt translation receipt changed")
    return json.loads(content)


def cancel_media_translation(session, media):
    receipt = media.metadata_json.get(RECEIPT, {})
    prep = session.get(Run, receipt.get("preparation_run_id")) if receipt else None
    if (
        not prep
        or prep.parent_run_id != media.id
        or prep.task_id != media.task_id
        or prep.executor_type != "media_translate"
    ):
        return
    review = session.get(Run, receipt.get("review_run_id")) if receipt.get("review_run_id") else None
    if (
        review
        and review.parent_run_id == prep.id
        and review.task_id == media.task_id
        and review.executor_type == "media_translation_apply"
        and review.status not in TERMINAL
    ):
        request_cancel(session, review)
    if prep.status not in TERMINAL:
        request_cancel(session, prep)


def cancel_translation_startup(session, consumer):
    """Cancel only a translation-created startup after its last consumer stops."""
    loads = session.scalars(
        select(Run)
        .join(RunDependency, RunDependency.prerequisite_id == Run.id)
        .where(
            RunDependency.run_id == consumer.id,
            Run.executor_type == "llama_load",
            Run.status.not_in(TERMINAL),
        )
    )
    for load in loads:
        origin_id = load.metadata_json.get("created_for_consumer")
        origin = session.get(Run, origin_id) if origin_id else None
        if not origin or origin.executor_type != "media_translate" or origin.task_id != load.task_id:
            continue
        if not active_dependents(session, load, exclude_run_id=consumer.id):
            request_cancel(session, load)


class ReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    effective: dict[str, str] = Field(min_length=1, max_length=4)


@router.post("/translations/{run_id}/review")
def review_translation(run_id: UUID, body: ReviewWrite, session: DB):
    from app.approvals import pending_approval, resolve_run_approval

    run = session.get(Run, str(run_id))
    if not run or run.executor_type != "media_translation_apply":
        raise HTTPException(404, "Translation review not found")
    approval = pending_approval(session, run.id)
    if (
        run.status != "waiting_for_approval"
        or not approval
        or digest(run.parameters["effective"]) != body.expected_hash
    ):
        raise HTTPException(409, "This translated prompt changed or was already reviewed")
    try:
        consumer(session, run)
        checked_effective(run.parameters["original"], body.effective)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    run.parameters = {**run.parameters, "effective": body.effective}
    approval.payload = {**approval.payload, "effective_hash": digest(body.effective)}
    append_event(
        session,
        run.id,
        "media.translation.reviewed",
        {"effective_hash": digest(body.effective), "edited": digest(body.effective) != body.expected_hash},
    )
    resolve_run_approval(session, run, "granted")
    session.commit()
    return run_dict(run)
