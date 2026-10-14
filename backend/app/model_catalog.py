"""Read-only projection over provider discovery and owned llama.cpp metadata."""

import re
from typing import Literal
from urllib.parse import quote, urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.models import ChatProvider, ModelDefinition, ModelFile
from app.serialize import iso


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_ref: str
    provider_key: str
    provider_name: str
    model_key: str
    display_name: str
    location: Literal["local", "external"]
    runtime_kind: Literal["llama.cpp", "local-server", "external"]
    availability: Literal[
        "ready", "available", "configured", "loads_when_needed", "loading", "needs_inspection", "unavailable"
    ]
    unavailable_reason: str = ""
    modalities: list[str]
    context_limit: int | None = None
    reasoning_capability: dict
    capability_provenance: dict
    config_version: str
    endpoint_host: str
    file_size_bytes: int | None = None
    quantization: str = ""


class CatalogProvider(BaseModel):
    key: str
    name: str
    location: Literal["local", "external"]
    builtin: bool
    enabled: bool
    discovered: bool
    error: str
    config_version: str


class ModelCatalog(BaseModel):
    models: list[CatalogModel]
    providers: list[CatalogProvider]


def build_catalog(session, *, discover_provider=None):
    from app.chat_providers import BUILTIN_KEY, _provider_models, ensure_builtin, provider_dict
    from app.llama import catalog

    ensure_builtin(session)
    session.commit()
    providers = list(
        session.scalars(select(ChatProvider).order_by(ChatProvider.builtin.desc(), ChatProvider.name))
    )
    if discover_provider is not None and discover_provider not in {p.key for p in providers}:
        raise HTTPException(404, "Chat provider not found")
    entries, summaries = [], []
    for provider in providers:
        public = provider_dict(provider)
        enabled = public["status"] == "available" and (
            provider.location != "external" or public["secret_present"]
        )
        models, error = [], None
        observed = enabled and provider.key == discover_provider
        if observed:
            models, error = _provider_models(session, provider)
        reported = set(models)
        if provider.default_model and provider.default_model not in models:
            models.append(provider.default_model)
        summaries.append(
            {
                "key": provider.key,
                "name": provider.name,
                "location": provider.location,
                "builtin": provider.builtin,
                "enabled": enabled,
                "discovered": observed and error is None,
                "error": error or ("Provider disabled or secret unavailable" if not enabled else ""),
                "config_version": iso(provider.updated_at),
            }
        )
        for model in sorted(set(models))[:200]:
            if not model or len(model) > 200 or model.startswith("llamacpp:"):
                continue
            available = "available" if observed and not error and model in reported else "configured"
            if not enabled or (observed and error):
                available = "unavailable"
            entries.append(
                CatalogModel(
                    model_ref=f"provider:{provider.key}:{quote(model, safe='')}",
                    provider_key=provider.key,
                    provider_name=provider.name,
                    model_key=model,
                    display_name=model,
                    location=provider.location,
                    runtime_kind="external" if provider.location == "external" else "local-server",
                    availability=available,
                    unavailable_reason=error
                    or ("Provider disabled or secret unavailable" if not enabled else ""),
                    modalities=["text"],
                    reasoning_capability={"kind": "unsupported", "verified": False},
                    capability_provenance={
                        "source": "endpoint.models" if observed and not error else "provider.configuration",
                        "modalities_verified": False,
                    },
                    config_version=iso(provider.updated_at),
                    endpoint_host=urlsplit(provider.endpoint).hostname or "",
                ).model_dump()
            )
        if provider.key != BUILTIN_KEY:
            continue
        owned = catalog(session)
        missing = [
            {
                "id": row.id,
                "model_key": "llamacpp:" + row.id,
                "name": row.filename,
                "missing_reason": "Model file is " + row.availability,
            }
            for row in session.scalars(
                select(ModelFile)
                .where(
                    ModelFile.category == "llm",
                    ModelFile.format == "gguf",
                    ModelFile.availability != "present",
                )
                .order_by(ModelFile.filename)
                .limit(200)
            )
            if not re.search(r"(^|[-_.])mmproj([-_.]|$)", row.filename, re.IGNORECASE)
        ]
        selected_ids = [model["id"] for model in [*owned["models"], *missing]]
        file_metadata = {
            row.id: row for row in session.scalars(select(ModelFile).where(ModelFile.id.in_(selected_ids)))
        }
        definitions = {
            row.file_id: row
            for row in session.scalars(
                select(ModelDefinition).where(ModelDefinition.file_id.in_(selected_ids))
            )
        }
        for model in [*owned["models"], *missing]:
            matches = [
                instance
                for instance in owned["instances"]
                if instance["metadata"].get("model_file_id") == model["id"]
            ]
            instance = next(
                (i for i in matches if i["status"] not in {"stopped", "failed"}),
                matches[0] if matches else None,
            )
            status = instance["status"] if instance else "stopped"
            availability = {
                "ready": "ready",
                "queued": "loading",
                "loading": "loading",
                "unknown": "needs_inspection",
                "stopping": "unavailable",
            }.get(status, "loads_when_needed")
            if not enabled:
                availability = "unavailable"
            if model.get("missing_reason"):
                availability = "unavailable"
            reason = (
                "Inspect runtime ownership in Models"
                if availability == "needs_inspection"
                else "Wait for the owned runtime to stop"
                if status == "stopping"
                else "Provider disabled or secret unavailable"
                if not enabled
                else ""
            )
            reason = model.get("missing_reason") or reason
            definition = definitions.get(model["id"])
            metadata = instance["metadata"] if instance else {}
            context = metadata.get("n_ctx_train")
            file = file_metadata.get(model["id"])
            entries.append(
                CatalogModel(
                    model_ref=model["model_key"],
                    provider_key=provider.key,
                    provider_name="Local · llama.cpp",
                    model_key=model["model_key"],
                    display_name=definition.name if definition else model["name"],
                    location="local",
                    runtime_kind="llama.cpp",
                    availability=availability,
                    unavailable_reason=reason,
                    modalities=["text", *(["image"] if model.get("vision_available") else [])],
                    context_limit=context if isinstance(context, int) and context > 0 else None,
                    reasoning_capability={"kind": "unsupported", "verified": False},
                    capability_provenance={
                        "source": "owned.model-registry",
                        "vision": "installed companion"
                        if model.get("vision_available")
                        else "not configured",
                        "runtime_instance_id": instance["id"] if instance else None,
                    },
                    config_version=iso(provider.updated_at),
                    endpoint_host="",
                    file_size_bytes=file.size_bytes if file else None,
                    quantization=file.quantization if file else "",
                ).model_dump()
            )
    return {"models": entries, "providers": summaries}
