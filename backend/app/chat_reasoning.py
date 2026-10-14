"""Bounded per-turn thinking, qualified for a specific owned model/runtime."""

import asyncio
import json
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.models import ModelDefinition, ModelFile, Run
from app.providers import ProviderError
from app.runner_client import RunnerClient
from app.runs import create_run, create_task, transition
from app.state import RunStatus

router = APIRouter(prefix="/api/llama")
DB = Annotated[Session, Depends(session_scope)]


class ReasoningOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    budget: StrictInt = Field(default=256, ge=32, le=1024)


@dataclass(frozen=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True)
class CompletionFinished:
    reason: str


def certificate(session, model):
    if not model.startswith("llamacpp:"):
        return None
    file_id = model.removeprefix("llamacpp:")
    file = session.get(ModelFile, file_id)
    definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == file_id))
    value = (definition.metadata_json or {}).get("reasoning_qualification") if definition else None
    if (
        not file
        or file.availability != "present"
        or not isinstance(value, dict)
        or value.get("verified") is not True
    ):
        return None
    source = session.get(Run, value.get("source_run_id", ""))
    if (
        source is None
        or source.status != "succeeded"
        or source.executor_type != "reasoning_check"
        or source.parameters.get("model") != model
    ):
        return None
    proof = source.metadata_json.get("reasoning_qualification", {})
    if any(
        value.get(key) != proof.get(key) for key in ("image_id", "template_sha256", "model_key", "verified")
    ):
        return None
    if (
        source.parameters.get("model_size") != file.size_bytes
        or source.parameters.get("model_mtime") != file.mtime
    ):
        return None
    if value.get("size_bytes") != file.size_bytes or value.get("mtime") != file.mtime:
        return None
    return value


def validated_options(session, model, options, max_tokens):
    if options is None:
        return None
    options = ReasoningOptions.model_validate(options)
    if not certificate(session, model):
        raise HTTPException(422, "Check thinking support for this local model in Models first")
    if options.enabled and max_tokens < options.budget + 256:
        raise HTTPException(422, "Increase output tokens to leave space for the final answer")
    return options.model_dump()


def runtime_identity(params):
    endpoint = params["endpoint"]
    if not endpoint.startswith("llamacpp:") or endpoint.startswith("llamacpp:pending:"):
        raise ProviderError("Thinking requires a ready owned runtime")
    report = RunnerClient().request("GET", "/v1/llama/" + endpoint.removeprefix("llamacpp:"))
    if report.get("status") != "ready" or not report.get("image_id") or not report.get("template_sha256"):
        raise ProviderError("Runtime thinking identity is unavailable; recheck model support")
    return {key: report[key] for key in ("image_id", "template_sha256")}


def check_binding(params, session):
    if params.get("reasoning") is None:
        return
    expected = params.get("reasoning_certificate")
    file = session.get(ModelFile, params["model"].removeprefix("llamacpp:"))
    if (
        not expected
        or expected.get("model_key") != params["model"]
        or not file
        or file.availability != "present"
        or file.size_bytes != expected.get("size_bytes")
        or file.mtime != expected.get("mtime")
    ):
        raise ProviderError("Model observation changed after thinking was qualified")
    identity = runtime_identity(params)
    if expected is None or any(identity[key] != expected.get(key) for key in identity):
        raise ProviderError("Model/runtime changed after thinking was qualified; recheck support")


@router.post("/models/{file_id}/reasoning-check", status_code=202)
def qualify(file_id: UUID, session: DB):
    from app.chat_providers import BUILTIN_KEY, snapshot_provider
    from app.llama import loadable_model, prepare_consumer
    from app.models import Conversation
    from app.runs import run_dict

    file = session.get(ModelFile, str(file_id))
    if not loadable_model(file):
        raise HTTPException(422, "Choose a present language-model GGUF")
    model = "llamacpp:" + file.id
    existing = session.scalars(
        select(Run).where(
            Run.executor_type == "reasoning_check",
            Run.status.in_(["queued", "claimed", "preparing", "running", "cancel_requested"]),
        )
    )
    for pending in existing:
        if pending.parameters.get("model") == model:
            return run_dict(pending)
    snapshot = snapshot_provider(session, Conversation(provider=BUILTIN_KEY, model=model))
    task = create_task(
        session,
        title="Check local thinking controls",
        prompt="Verify bounded local thinking on/off",
        capability="model.reasoning",
    )
    run = create_run(
        session,
        task,
        run_type="model",
        capability="model.reasoning",
        executor_type="reasoning_check",
        execution_target="container",
        parameters={
            **snapshot,
            "model": model,
            "temperature": 0,
            "max_tokens": 768,
            "messages": [
                {"role": "user", "content": "What is 17 times 23? Give only the final numeric answer."}
            ],
            "model_size": file.size_bytes,
            "model_mtime": file.mtime,
        },
        permissions=["manage_models"],
        retry_class="inspect",
    )
    prepare_consumer(session, run)
    session.commit()
    return run_dict(run)


class ReasoningCheckExecutor:
    name = "reasoning_check"

    def execute(self, session, run):
        from app.permissions import require

        require(run.effective_permissions, "manage_models")
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        transition(session, run, RunStatus.RUNNING, event_type="executor.started", payload={})
        session.commit()
        result = asyncio.run(self.probe(session, run))
        if result is None:
            return "done"
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        if run.status != "running":
            raise ProviderError("Qualification lost its active lease before publication")
        result = {**result, "model_key": run.parameters["model"]}
        file = session.get(ModelFile, run.parameters["model"].removeprefix("llamacpp:"))
        if (
            file is None
            or file.size_bytes != run.parameters["model_size"]
            or file.mtime != run.parameters["model_mtime"]
            or file.availability != "present"
        ):
            raise ProviderError("Model observation changed during qualification")
        definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == file.id))
        if definition is None:
            definition = ModelDefinition(
                name=file.filename, file_id=file.id, category="llm", status="unverified"
            )
            session.add(definition)
        definition.metadata_json = {
            **(definition.metadata_json or {}),
            "reasoning_qualification": {
                **result,
                "size_bytes": file.size_bytes,
                "mtime": file.mtime,
                "source_run_id": run.id,
            },
        }
        definition.updated_at = utcnow()
        run.metadata_json = {**run.metadata_json, "reasoning_qualification": result}
        from app.artifacts import adopt_existing
        from app.config import get_settings
        from app.paths import safe_join

        relative = f"runs/{run.id}/reasoning-qualification.json"
        output = safe_join(get_settings().data_dir, relative)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as handle:
            json.dump(result, handle)
        adopt_existing(
            session,
            relative_path=relative,
            artifact_type="json",
            mime_type="application/json",
            original_filename="reasoning-qualification.json",
            run_id=run.id,
        )
        transition(session, run, RunStatus.SUCCEEDED, event_type="model.reasoning_qualified", payload=result)
        return "done"

    async def probe(self, session, run):
        from app.events import append_event
        from app.local_provider import LocalChatProvider

        identity = runtime_identity(run.parameters)
        results = []
        for enabled in (False, True):
            options = {"enabled": enabled, "budget": 128}
            stream = LocalChatProvider().stream(
                **{
                    key: run.parameters[key]
                    for key in ("endpoint", "model", "temperature", "max_tokens", "messages")
                },
                reasoning=options,
            )
            thinking, final = 0, ""
            pending = None
            try:
                async with asyncio.timeout(300):
                    while True:
                        session.refresh(run)
                        if run.status == "cancel_requested":
                            transition(
                                session, run, RunStatus.CANCELED, event_type="run.canceled", payload={}
                            )
                            session.commit()
                            return None
                        session.commit()
                        if pending is None:
                            pending = asyncio.create_task(anext(stream))
                        ready, _ = await asyncio.wait([pending], timeout=0.25)
                        if not ready:
                            continue
                        try:
                            delta = pending.result()
                        except StopAsyncIteration:
                            break
                        finally:
                            pending = None
                        if isinstance(delta, CompletionFinished):
                            if delta.reason == "length":
                                raise ProviderError("Qualification exhausted the output budget")
                            continue
                        if isinstance(delta, ReasoningDelta):
                            thinking += len(delta.text)
                        else:
                            final += delta
                        if len(final) > 8192 or thinking > 16384:
                            raise ProviderError("Qualification output exceeded its bound")
            finally:
                if pending is not None:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                await stream.aclose()
            if not final.strip() or (enabled and thinking == 0) or (not enabled and thinking):
                raise ProviderError(
                    "This model did not demonstrate bounded thinking on/off with a final answer"
                )
            results.append(
                {"enabled": enabled, "thinking_characters": thinking, "final_characters": len(final)}
            )
            append_event(session, run.id, "model.reasoning_probe", results[-1])
            session.commit()
        if runtime_identity(run.parameters) != identity:
            raise ProviderError("Runtime identity changed during qualification")
        return {**identity, "probes": results, "kind": "toggle", "verified": True}
