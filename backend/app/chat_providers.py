"""Persisted chat providers with secret references and explicit selection."""

from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope, utcnow
from app.local_provider import (
    LocalChatProvider,
    discover_models,
    local_endpoint,
    model_endpoint,
    validate_endpoint,
)
from app.model_catalog import ModelCatalog
from app.models import ChatProvider, Conversation
from app.paths import PathBoundaryError
from app.providers import ProviderError
from app.secrets import (
    authorization_headers,
    clear_secret_file,
    parse_secret_ref,
    public_secret,
    store_secret_file,
)
from app.serialize import iso

router = APIRouter(prefix="/api/chat")
DB = Annotated[Session, Depends(session_scope)]
BUILTIN_KEY = LocalChatProvider.key
_KEY = re.compile(r"^[a-z][a-z0-9-]{1,78}$")


class ProviderWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["openai-compatible"] = "openai-compatible"
    location: Literal["local", "external"]
    endpoint: str = Field(min_length=8, max_length=500)
    secret_ref: str = Field(default="", max_length=200)
    secret: str | None = Field(default=None, max_length=4096)
    default_model: str = Field(default="", max_length=200)
    enabled: StrictBool = True

    @model_validator(mode="after")
    def validate_provider(self):
        if not _KEY.fullmatch(self.key) or self.key == BUILTIN_KEY:
            raise ValueError("Choose a unique lowercase provider key other than the built-in local provider")
        try:
            parse_secret_ref(self.secret_ref)
        except (ValueError, PathBoundaryError) as exc:
            raise ValueError(str(exc)) from exc
        if self.secret is not None and not self.secret.strip():
            raise ValueError("A stored secret cannot be empty")
        if self.location == "external" and not (self.secret_ref or self.secret):
            raise ValueError("External providers require a secret reference or a stored secret")
        try:
            self.endpoint = validate_endpoint(self.endpoint, self.location)
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc
        return self


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    endpoint: str | None = Field(default=None, min_length=8, max_length=500)
    secret_ref: str | None = Field(default=None, max_length=200)
    secret: str | None = Field(default=None, max_length=4096)
    clear_secret: StrictBool = False
    default_model: str | None = Field(default=None, max_length=200)
    enabled: StrictBool | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if self.secret is not None and not self.secret.strip():
            raise ValueError("A stored secret cannot be empty")
        if self.secret_ref is not None:
            try:
                self.secret_ref = parse_secret_ref(self.secret_ref)
            except (ValueError, PathBoundaryError) as exc:
                raise ValueError(str(exc)) from exc
        if self.clear_secret and (self.secret or self.secret_ref):
            raise ValueError("Clearing a secret cannot be combined with a new secret")
        return self


def ensure_builtin(session: Session) -> ChatProvider:
    secret_ref = "env:AI_STATION_LLM_API_KEY" if get_settings().llm_api_key else ""
    try:
        endpoint = local_endpoint()
    except ProviderError:
        endpoint = (get_settings().llm_host_base_url or get_settings().llm_base_url).rstrip("/")
    row = session.scalar(select(ChatProvider).where(ChatProvider.key == BUILTIN_KEY))
    if row is None:
        row = ChatProvider(
            key=BUILTIN_KEY,
            name="Local OpenAI-compatible",
            kind="openai-compatible",
            location="local",
            endpoint=endpoint,
            secret_ref=secret_ref,
            default_model=get_settings().llm_model,
            enabled=True,
            builtin=True,
        )
        session.add(row)
        session.flush()
        return row
    values = {
        "endpoint": endpoint,
        "secret_ref": secret_ref,
        "default_model": get_settings().llm_model,
        "enabled": True,
    }
    if any(getattr(row, key) != value for key, value in values.items()):
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = utcnow()
    return row


def normalize_provider_key(identifier: str) -> str:
    if not identifier or identifier in {"openai-compatible", BUILTIN_KEY}:
        return BUILTIN_KEY
    return identifier


def get_provider(session: Session, identifier: str) -> ChatProvider:
    ensure_builtin(session)
    identifier = normalize_provider_key(identifier)
    row = session.get(ChatProvider, identifier)
    if row is None:
        row = session.scalar(select(ChatProvider).where(ChatProvider.key == identifier))
    if row is None:
        raise HTTPException(404, "Chat provider not found")
    return row


def provider_dict(row: ChatProvider, *, models: list[str] | None = None, error: str | None = None) -> dict:
    status = (
        "available"
        if row.enabled and (not row.secret_ref or public_secret(row.secret_ref)["secret_present"])
        else "unavailable"
    )
    if error:
        status = "unavailable"
    payload = {
        "id": row.id,
        "key": row.key,
        "name": row.name,
        "kind": row.kind,
        "location": row.location,
        "endpoint": row.endpoint,
        "default_model": row.default_model,
        "enabled": row.enabled,
        "builtin": row.builtin,
        "status": status,
        "error": error,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        **public_secret(row.secret_ref),
    }
    if models is not None:
        payload["models"] = models
        if models:
            payload["status"] = "available"
    return payload


def snapshot_provider(session: Session, conversation: Conversation) -> dict:
    row = get_provider(session, conversation.provider)
    if not row.enabled:
        raise HTTPException(409, "The selected chat provider is disabled")
    if conversation.model.startswith("llamacpp:") and row.key != BUILTIN_KEY:
        raise HTTPException(409, "Owned llama.cpp models require the local provider")
    try:
        endpoint = (
            model_endpoint(conversation.model, session)
            if conversation.model.startswith("llamacpp:")
            else validate_endpoint(row.endpoint, row.location)
        )
        if row.secret_ref or row.location == "external":
            authorization_headers(row.secret_ref, required=row.location == "external")
        elif row.builtin:
            validate_endpoint(local_endpoint(), "local")
    except ProviderError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "provider": row.key,
        "provider_id": row.id,
        "location": row.location,
        "endpoint": endpoint,
        "secret_ref": row.secret_ref,
        "provider_config_version": iso(row.updated_at),
    }


def chat_permissions(snapshot: dict, extra: list[str] | None = None) -> list[str]:
    granted = list(extra or [])
    if snapshot.get("location") == "external" and "external_ai" not in granted:
        granted.append("external_ai")
    return granted


def bind_completion(session: Session, params: dict) -> dict:
    location = params.get("location") or "local"
    provider_key = normalize_provider_key(params.get("provider") or BUILTIN_KEY)
    if provider_key == BUILTIN_KEY:
        live_endpoint = (
            model_endpoint(params["model"], session)
            if str(params.get("model", "")).startswith("llamacpp:")
            else local_endpoint()
        )
        live_secret = "env:AI_STATION_LLM_API_KEY" if get_settings().llm_api_key else ""
    else:
        row = session.get(ChatProvider, params.get("provider_id")) if params.get("provider_id") else None
        if row is None or row.key != provider_key or not row.enabled:
            raise ProviderError("The selected chat provider is no longer available")
        live_endpoint = (
            model_endpoint(params["model"], session)
            if str(params.get("model", "")).startswith("llamacpp:")
            else validate_endpoint(row.endpoint, row.location)
        )
        live_secret = row.secret_ref
        location = row.location
    if live_endpoint != params.get("endpoint") or live_secret != params.get("secret_ref", ""):
        raise ProviderError("The configured endpoint changed after this run was queued")
    headers = authorization_headers(live_secret, required=location == "external")
    return {"headers": headers, "location": location}


def completion_stream(session, params):
    from app.chat_reasoning import check_binding

    check_binding(params, session)
    bound = bind_completion(session, params)
    return LocalChatProvider().stream(
        endpoint=params["endpoint"],
        messages=params["messages"],
        model=params["model"],
        temperature=params["temperature"],
        max_tokens=params["max_tokens"],
        headers=bound["headers"],
        location=bound["location"],
        **({"reasoning": params["reasoning"]} if params.get("reasoning") is not None else {}),
        **({"json_output": True} if params.get("json_output") is True else {}),
    )


def require_external_permission(run) -> None:
    from app.permissions import PermissionDenied, require

    if run.parameters.get("location") == "external":
        try:
            require(run.effective_permissions, "external_ai")
        except PermissionDenied as exc:
            raise ProviderError(str(exc)) from exc


def _apply_secret(row: ChatProvider, *, secret: str | None, secret_ref: str, clear: bool) -> None:
    previous = row.secret_ref
    if clear:
        clear_secret_file(previous)
        row.secret_ref = ""
        return
    if secret:
        clear_secret_file(previous)
        row.secret_ref = store_secret_file(row.id, secret)
        return
    parsed = parse_secret_ref(secret_ref)
    if parsed != previous:
        clear_secret_file(previous)
    row.secret_ref = parsed


def _provider_models(session: Session, row: ChatProvider) -> tuple[list[str], str | None]:
    error = None
    models: list[str] = []
    try:
        if row.secret_ref or row.location == "external":
            headers = authorization_headers(row.secret_ref, required=row.location == "external")
        else:
            headers = {}
        if row.key == BUILTIN_KEY:
            models = LocalChatProvider().models()
            from app.llama import instances

            models = list(models) + [
                "llamacpp:" + item.metadata_json["model_file_id"]
                for item in instances(session)
                if item.status == "ready" and item.metadata_json.get("model_file_id")
            ]
        else:
            models = discover_models(row.endpoint, headers=headers)
    except ProviderError as exc:
        error = str(exc)
        models = []
    return models, error


@router.get("/provider")
def builtin_provider(session: DB):
    row = ensure_builtin(session)
    session.commit()
    try:
        local_endpoint()
    except ProviderError as exc:
        raise HTTPException(409, str(exc)) from exc
    models, error = _provider_models(session, row)
    return provider_dict(row, models=models, error=error)


@router.get("/providers")
def list_providers(session: DB):
    ensure_builtin(session)
    session.commit()
    rows = list(
        session.scalars(select(ChatProvider).order_by(ChatProvider.builtin.desc(), ChatProvider.name))
    )
    return [provider_dict(row) for row in rows]


@router.get("/model-catalog", response_model=ModelCatalog)
def model_catalog(session: DB, discover_provider: Annotated[str | None, Query(max_length=80)] = None):
    from app.model_catalog import build_catalog

    return build_catalog(session, discover_provider=discover_provider)


@router.post("/providers", status_code=201)
def create_provider(body: ProviderWrite, session: DB):
    ensure_builtin(session)
    if session.scalar(select(ChatProvider).where(ChatProvider.key == body.key)):
        raise HTTPException(409, "A chat provider with this key already exists")
    row = ChatProvider(
        key=body.key,
        name=body.name,
        kind=body.kind,
        location=body.location,
        endpoint=body.endpoint,
        default_model=body.default_model,
        enabled=body.enabled,
        builtin=False,
    )
    session.add(row)
    session.flush()
    try:
        _apply_secret(row, secret=body.secret, secret_ref=body.secret_ref, clear=False)
    except (ValueError, PathBoundaryError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if row.location == "external" and not row.secret_ref:
        raise HTTPException(422, "External providers require a secret reference or a stored secret")
    session.commit()
    return provider_dict(row)


@router.get("/providers/{provider_id}")
def provider_detail(provider_id: str, session: DB):
    row = get_provider(session, provider_id)
    session.commit()
    models, error = _provider_models(session, row)
    return provider_dict(row, models=models, error=error)


@router.patch("/providers/{provider_id}")
def edit_provider(provider_id: str, body: ProviderPatch, session: DB):
    row = get_provider(session, provider_id)
    if row.builtin:
        if (
            body.endpoint is not None
            or body.secret is not None
            or body.secret_ref is not None
            or body.clear_secret
        ):
            raise HTTPException(409, "The built-in local provider is configured with environment settings")
        if body.enabled is False:
            raise HTTPException(409, "The built-in local provider cannot be disabled")
    if body.name is not None:
        row.name = body.name
    if body.default_model is not None:
        row.default_model = body.default_model
    if body.enabled is not None and not row.builtin:
        row.enabled = body.enabled
    if body.endpoint is not None:
        try:
            row.endpoint = validate_endpoint(body.endpoint, row.location)
        except ProviderError as exc:
            raise HTTPException(422, str(exc)) from exc
    if body.secret is not None or body.secret_ref is not None or body.clear_secret:
        try:
            _apply_secret(
                row,
                secret=body.secret,
                secret_ref=body.secret_ref if body.secret_ref is not None else row.secret_ref,
                clear=body.clear_secret,
            )
        except (ValueError, PathBoundaryError) as exc:
            raise HTTPException(422, str(exc)) from exc
    if row.location == "external" and not row.secret_ref:
        raise HTTPException(422, "External providers require a secret reference or a stored secret")
    row.updated_at = utcnow()
    session.commit()
    return provider_dict(row)


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: UUID, session: DB):
    row = get_provider(session, str(provider_id))
    if row.builtin:
        raise HTTPException(409, "The built-in local provider cannot be removed")
    used = session.scalar(select(Conversation.id).where(Conversation.provider == row.key).limit(1))
    if used:
        raise HTTPException(409, "This provider is still selected by a conversation")
    clear_secret_file(row.secret_ref)
    session.delete(row)
    session.commit()
