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
from sqlalchemy import select
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
from app.models import Artifact, ModelDefinition, ModelFile, Run, RunDependency, RuntimeInstance
from app.paths import safe_join
from app.permissions import require
from app.personal_settings import preference_row
from app.runs import create_run, mark_failed, request_cancel, run_dict, transition
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/generation", tags=["generation"])
DB = Annotated[Session, Depends(session_scope)]
KEY = "media_prompt_translation"
RECEIPT = "prompt_translation"
DEFAULT = {"revision": 0, "enabled": False, "model": "", "target_language": "en"}


def preferences(session):
    row = preference_row(session, KEY)
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
    current = preference_row(session, KEY, default=DEFAULT, lock=True)
    if current.value["revision"] != body.revision:
        raise HTTPException(409, "Generation settings changed; refresh before saving")
    current.value = {**body.model_dump(), "revision": body.revision + 1}
    session.commit()
    return preferences(session)


def image_fields(run):
    params = run.parameters
    if run.executor_type == "echomimic":
        return {"prompt": params["prompt"]}
    if run.executor_type == "mmaudio_effects":
        from app.effects import descriptive_fields

        return descriptive_fields(params)
    if run.executor_type == "wan_video":
        return {key: params[key] for key in ["prompt", "negative_prompt"] if params.get(key)}
    if run.executor_type == "ace_step_music":
        return {"caption": params["caption"]}
    if params.get("mode") == "upscale":
        return {}
    keys = ["edit_prompt" if params.get("mode") == "img2img" else "prompt", "negative", "video_prompt"]
    return {key: params[key] for key in keys if params.get(key)}


def source_hash(run, fields):
    if run.executor_type == "echomimic":
        return digest(
            {
                "executor": run.executor_type,
                "fields": fields,
                "gpu": run.requested_gpu,
                "inputs": {
                    key: value
                    for key, value in run.parameters.items()
                    if key not in {"prompt", "translation", "previous_video_run_id"}
                },
            }
        )
    keys = {
        "mmaudio_effects": [
            "video",
            "video_artifact_id",
            "profile",
            "observation",
            "steps",
            "cfg",
            "seed",
            "backend",
            "parent_artifact_ids",
        ],
        "wan_video": [
            "image_relative",
            "parent_artifact_ids",
            "media_inputs",
            "backend",
            "profile_observation",
            "frames",
            "width",
            "height",
            "steps",
            "cfg",
            "seed",
            "memory_profile",
            "media_segment",
            "scene_index",
        ],
        "ace_step_music": [
            "lyrics",
            "instrumental",
            "duration_seconds",
            "seed",
            "backend",
            "model_revision",
            "code_revision",
            "profile_sha256",
        ],
    }.get(run.executor_type)
    if keys is not None:
        inputs = {key: run.parameters.get(key) for key in keys}
        if run.executor_type == "mmaudio_effects" and run.parameters.get("cues"):
            inputs["cue_timing"] = [
                {k: c[k] for k in ("start_frame", "end_frame")} for c in run.parameters["cues"]
            ]
        if run.executor_type == "wan_video":
            # Preserve the exact input identity of pre-strategy receipts, while
            # binding new plans to their frozen conditioning policy.
            for key in ("continuation_strategy", "guidance_observation"):
                if key in run.parameters:
                    inputs[key] = run.parameters[key]
        return digest(
            {
                "executor": run.executor_type,
                "fields": fields,
                "gpu": run.requested_gpu,
                "inputs": inputs,
            }
        )
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


def enqueue_translation(session, media, options=None, *, policy=None, additional_consumers=()):
    options = TranslationOptions.model_validate(options or {})
    policy = dict(policy or preferences(session))
    enabled = policy["enabled"] if options.mode == "inherit" else options.mode == "on"
    fields = image_fields(media)
    if not (enabled or options.enhance) or not fields:
        return None
    if media.executor_type not in {
        "photo_pipe",
        "wan_video",
        "ace_step_music",
        "echomimic",
        "mmaudio_effects",
    }:
        raise ValueError("Unsupported media translation consumer")
    system = SYSTEM
    template = None
    if options.enhance:
        from app.prompt_enhancement import recipe

        template, system = recipe(media, translate=enabled)
        frozen = policy.get("enhancement_template")
        if frozen is not None and frozen != template:
            raise ValueError("The saved enhancement template requires inspection")
        policy.update(
            operation="enhance",
            enhancement_template=template,
            translate_descriptions=enabled,
            target_language="en" if enabled else "original",
        )
    limits = {
        key: 500
        if media.executor_type == "mmaudio_effects" and key.startswith("cue_")
        else 512
        if key == "caption"
        else 2000
        if media.executor_type in {"wan_video", "echomimic", "mmaudio_effects"}
        else FIELD_LIMITS.get(key, 10000)
        for key in fields
    }
    targets = []
    for item in additional_consumers:
        if (
            item.id == media.id
            or item.task_id != media.task_id
            or item.executor_type != media.executor_type
            or item.status != "queued"
            or image_fields(item) != fields
        ):
            raise ValueError("Translation group has mismatched media consumers")
        if template is not None and recipe(item, translate=enabled)[0] != template:
            raise ValueError("Enhancement group has mismatched generator templates")
        targets.append({"run_id": item.id, "source_hash": source_hash(item, fields)})
    if len(targets) > 100 or len({item["run_id"] for item in targets}) != len(targets):
        raise ValueError("Translation group exceeds its unique consumer bound")
    validate_model(session, policy["model"])
    policy.setdefault("model_label", translator_label(session, policy["model"]))
    encoded, tokens = encode_fields(
        fields, options.protected_terms, max_fields=18 if media.executor_type == "mmaudio_effects" else 4
    )
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
            "additional_consumers": targets,
            "field_limits": limits,
            "options": options.model_dump(),
            "temperature": 0.0,
            "system_prompt": system,
            "max_tokens": 8192
            if media.executor_type == "mmaudio_effects" and media.parameters.get("cues")
            else 4096,
            "json_output": True,
            "require_complete": True,
        },
    )
    from app.llama import prepare_consumer

    prepare_consumer(session, child)
    for item in [media, *additional_consumers]:
        depend_on(session, item, child)
        item.metadata_json = {
            **item.metadata_json,
            RECEIPT: {
                "preparation_run_id": child.id,
                "origin_run_id": item.id,
                "original": fields,
                "policy": policy,
                "options": options.model_dump(),
                "status": "queued",
            },
        }
        append_event(session, item.id, "media.translation.queued", {"preparation_run_id": child.id})
    return child


def consumer(session, run):
    media = session.get(Run, run.parameters.get("consumer_run_id"))
    if (
        not media
        or media.status != "queued"
        or media.task_id != run.task_id
        or media.executor_type
        not in {"photo_pipe", "wan_video", "ace_step_music", "echomimic", "mmaudio_effects"}
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


def grouped_consumers(session, run, media):
    result = [media]
    for target in run.parameters.get("additional_consumers", []):
        item = session.get(Run, target["run_id"], populate_existing=True)
        prep_id = run.id if run.executor_type == "media_translate" else run.parent_run_id
        if (
            not item
            or item.task_id != media.task_id
            or item.executor_type != media.executor_type
            or item.status != "queued"
            or image_fields(item) != run.parameters["original"]
            or source_hash(item, run.parameters["original"]) != target["source_hash"]
            or item.metadata_json.get(RECEIPT, {}).get("preparation_run_id") != prep_id
        ):
            raise ValueError("A grouped media request changed during translation")
        result.append(item)
    return result


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
        "source_hash": source_hash(media, run.parameters["original"]),
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


def checked_effective(original, effective, limits=None):
    if set(effective) != set(original) or any(
        not isinstance(text, str)
        or not text.strip()
        or len(text) > (limits or FIELD_LIMITS).get(key, 10000)
        or "\0" in text
        for key, text in effective.items()
    ):
        raise ValueError("Reviewed translation has invalid descriptive fields")


def apply_effective(session, run, media, effective, *, reviewed=False):
    checked_effective(run.parameters["original"], effective, run.parameters.get("field_limits"))
    targets = grouped_consumers(session, run, media)
    for item in targets:
        apply_one(session, run, item, effective, reviewed=reviewed)


def set_descriptions(media, fields):
    if media.executor_type == "mmaudio_effects":
        from app.effects import apply_descriptions

        media.parameters = apply_descriptions(media.parameters, fields)
    else:
        media.parameters = {**media.parameters, **fields}


def apply_one(session, run, media, effective, *, reviewed=False):
    artifact = save_receipt(session, run, media, effective, reviewed=reviewed)
    set_descriptions(media, effective)
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
            targets = grouped_consumers(session, run, media)
            checked_effective(run.parameters["original"], effective, run.parameters.get("field_limits"))
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
                        "additional_consumers": run.parameters.get("additional_consumers", []),
                        "field_limits": run.parameters.get("field_limits", FIELD_LIMITS),
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
                for identifier in run.parameters.get("barrier_consumer_ids", []):
                    item = session.get(Run, identifier)
                    if (
                        not item
                        or item.task_id != media.task_id
                        or item.executor_type not in {"wan_video", "echomimic"}
                        or not item.parameters.get("internal_media")
                        or item.status != "queued"
                    ):
                        raise ValueError("Film review barrier has a changed consumer")
                    depend_on(session, item, review)
                for item in targets:
                    depend_on(session, item, review)
                    item.metadata_json = {
                        **item.metadata_json,
                        RECEIPT: {
                            **item.metadata_json[RECEIPT],
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


def validate_media_translation(session, run, *, _seen=()):
    receipt = run.metadata_json.get(RECEIPT)
    if not receipt:
        return
    if receipt.get("reused_from_run_id"):
        from app.media_retry_intent import REUSED, reuse_source

        if run.id in _seen or len(_seen) >= 16:
            raise ValueError("Translation reuse exceeds its inspection bound")
        source = reuse_source(session, run, receipt[REUSED])
        validate_media_translation(session, source, _seen=(*_seen, run.id))
        if (
            receipt != {**source.metadata_json.get(RECEIPT, {}), REUSED: source.id}
            or image_fields(run) != receipt.get("effective")
            or source_hash(run, receipt["original"]) != source_hash(source, receipt["original"])
        ):
            raise ValueError("Reused translation differs from the verified source")
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


def decorate_output(run, artifact):
    receipt = run.metadata_json.get(RECEIPT)
    if not receipt:
        return
    artifact.metadata_json = {**artifact.metadata_json, RECEIPT: receipt}
    identifier = receipt.get("artifact_id")
    if identifier and identifier not in artifact.parent_artifact_ids:
        artifact.parent_artifact_ids = [*artifact.parent_artifact_ids, identifier]


def enqueue_groups(session, entries):
    """One inference per identical same-Task instruction group; all groups gate the film."""
    groups = {}
    for media, options, policy in entries:
        policy = dict(policy or preferences(session))
        key = digest([image_fields(media), options, policy])
        groups.setdefault(key, []).append((media, options, policy))
    preparations, primary_ids = [], []
    for items in groups.values():
        primary, options, policy = items[0]
        prep = enqueue_translation(
            session, primary, options, policy=policy, additional_consumers=[item[0] for item in items[1:]]
        )
        if prep:
            preparations.append(prep)
            primary_ids.append(primary.id)
    for media, _, _ in entries:
        for prep in preparations:
            depend_on(session, media, prep)
    if len(entries) > 1:
        for prep in preparations:
            prep.parameters = {**prep.parameters, "barrier_consumer_ids": [entry[0].id for entry in entries]}
    return primary_ids


def recovery_options(receipt, choice):
    options = {**receipt.get("options", {}), "mode": "on" if choice == "retry" else "off"}
    if receipt.get("options", {}).get("enhance"):
        options["mode"] = receipt["options"].get("mode", "inherit") if choice == "retry" else "off"
        if choice != "retry":
            options["enhance"] = False
    return options


def prepare_retry(session, source, retry, choice):
    receipt = source.metadata_json.get(RECEIPT)
    if not receipt:
        return None
    if choice == "reuse":
        try:
            validate_media_translation(session, source)
        except (ValueError, OSError) as exc:
            raise HTTPException(
                409, "Saved translation is unavailable. Choose Retry translation or Use original"
            ) from exc
        retry.metadata_json = {**retry.metadata_json, RECEIPT: receipt}
        return None
    set_descriptions(retry, receipt["original"])
    options = recovery_options(receipt, choice)
    if choice == "retry":
        return retry, options, receipt["policy"]
    retry.parameters = {**retry.parameters, "translation": {**options, "review": False}}
    retry.metadata_json = {
        **retry.metadata_json,
        RECEIPT: {
            key: value
            for key, value in receipt.items()
            if key not in {"artifact_id", "artifact_sha256", "review_run_id", "reused_from_run_id"}
        }
        | {"status": "original", "effective": receipt["original"], "bypass_of": source.id},
    }
    append_event(
        session, retry.id, "media.translation.bypassed", {"original_run_id": source.id, "by": "user"}
    )
    return None


class TranslationRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translation: Literal["reuse", "retry", "original"] = "reuse"
    client_request_id: UUID | None = None


@router.post("/media/{run_id}/retry", status_code=202)
def retry_media(run_id: UUID, body: TranslationRetry, session: DB):
    from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable

    source = session.get(Run, str(run_id))
    if source and source.executor_type == "photo_pipe":
        from app.images import ImageRetry, retry_image

        return retry_image(run_id, session, ImageRetry.model_validate(body.model_dump()))
    if not source or source.executor_type not in {
        "wan_video",
        "ace_step_music",
        "echomimic",
        "mmaudio_effects",
    }:
        raise HTTPException(404, "Media Run not found")
    if source.parameters.get("internal_media"):
        raise HTTPException(409, "Resume the whole film instead of an individual segment")
    if source.status not in {"failed", "canceled", "interrupted"}:
        raise HTTPException(409, "Inspect active or completed media before retrying")
    if body.translation != "reuse" and not source.metadata_json.get(RECEIPT):
        raise HTTPException(409, "This Run has no translation to resolve")
    identity = {"id": str(body.client_request_id), "translation": body.translation}

    def previous():
        from app.media_retry_intent import existing_fresh, locked_source

        locked_source(session, source)
        if fresh := existing_fresh(session, source, identity, replayable=bool(body.client_request_id)):
            return fresh
        item = session.scalar(
            select(Run).where(Run.parent_run_id == source.id, Run.executor_type == source.executor_type)
        )
        if item and body.client_request_id and item.metadata_json.get("media_retry_request") == identity:
            return item
        if item:
            raise HTTPException(409, "A retry already exists; inspect that Run")
        return None

    if item := previous():
        return run_dict(item)
    session.commit()
    try:
        info = RunnerClient().inspect_process(source.id)
        if info.get("alive") or info.get("completion_pending"):
            raise HTTPException(409, "The original process still requires inspection")
    except RunnerUnavailable as exc:
        raise HTTPException(409, "Runner must be reachable before retrying") from exc
    except RunnerError as exc:
        if exc.status_code != 404:
            raise HTTPException(409, "Cannot confirm that the original process stopped") from exc
    session.refresh(source)
    if item := previous():
        return run_dict(item)
    from app.media_retry_intent import finish_retry, task_for_retry

    task = task_for_retry(session, source, body.translation)
    retry_parameters = dict(source.parameters)
    if source.executor_type == "mmaudio_effects" and source.agent_id is None:
        # An inspected new manual attempt gets its own execution budget. Repeated
        # dispatch of one Run still cannot extend that Run's native deadline.
        retry_parameters.pop("execution_deadline_at", None)
    retry = create_run(
        session,
        task,
        run_type=source.run_type,
        capability=source.capability,
        executor_type=source.executor_type,
        execution_target=source.execution_target,
        parameters=retry_parameters,
        requested_gpu=source.requested_gpu,
        requested_resources=dict(source.requested_resources),
        permissions=list(source.effective_permissions),
        retry_class="inspect",
        parent_run_id=source.id if task.id == source.task_id else None,
        metadata={"media_retry_request": identity},
    )
    entry = prepare_retry(session, source, retry, body.translation)
    if entry:
        enqueue_groups(session, [entry])
    finish_retry(session, source, retry, identity)
    session.commit()
    return run_dict(retry)


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
    effective: dict[str, str] = Field(min_length=1, max_length=18)


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
        grouped_consumers(session, run, consumer(session, run))
        checked_effective(run.parameters["original"], body.effective, run.parameters.get("field_limits"))
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
