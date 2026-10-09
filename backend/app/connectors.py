"""Named HTTP GET connectors with secret references and inspectable health Runs."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.events import append_event
from app.http_fetch import fetch_public, public_url
from app.models import Connector, Run
from app.paths import PathBoundaryError
from app.providers import ProviderError
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.secrets import (
    authorization_headers,
    clear_secret_file,
    parse_secret_ref,
    public_secret,
    store_secret_file,
)
from app.serialize import iso
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/connectors", tags=["connectors"])
DB = Annotated[Session, Depends(session_scope)]
_KEY = re.compile(r"^[a-z][a-z0-9-]{1,78}$")
HTTP_CAPABILITIES = ["http.get"]
KINDS = (
    {
        "kind": "http",
        "operational": True,
        "capabilities": HTTP_CAPABILITIES,
        "summary": "GET one reviewed public URL. Optional secret reference becomes a Bearer token.",
    },
    {
        "kind": "browser",
        "operational": False,
        "capabilities": [],
        "summary": "Browser automation is not enabled.",
    },
    {
        "kind": "github",
        "operational": False,
        "capabilities": [],
        "summary": "GitHub remains the existing publication adapter; it is not a general connector yet.",
    },
    {
        "kind": "email",
        "operational": False,
        "capabilities": [],
        "summary": "Email is not enabled.",
    },
    {
        "kind": "calendar",
        "operational": False,
        "capabilities": [],
        "summary": "Calendar is not enabled.",
    },
    {
        "kind": "social",
        "operational": False,
        "capabilities": [],
        "summary": "Social networks are not enabled.",
    },
)
KIND_INDEX = {item["kind"]: item for item in KINDS}


def kind_spec(kind: str):
    spec = KIND_INDEX.get(kind)
    if spec is None:
        raise HTTPException(422, "Unknown connector kind")
    if not spec["operational"]:
        raise HTTPException(409, f"{kind} connectors are not enabled")
    return spec


class ConnectorWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["http"] = "http"
    url: str = Field(min_length=8, max_length=2000)
    secret_ref: str = Field(default="", max_length=200)
    secret: str | None = Field(default=None, max_length=4096)
    enabled: StrictBool = True

    @model_validator(mode="after")
    def validate_connector(self):
        if not _KEY.fullmatch(self.key):
            raise ValueError("Choose a unique lowercase connector key")
        if public_url(self.url) is None:
            raise ValueError("HTTP connectors require one public http(s) URL on port 80 or 443")
        try:
            self.secret_ref = parse_secret_ref(self.secret_ref)
        except (ValueError, PathBoundaryError) as exc:
            raise ValueError(str(exc)) from exc
        if self.secret is not None and not self.secret.strip():
            raise ValueError("A stored secret cannot be empty")
        return self


class ConnectorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    secret_ref: str | None = Field(default=None, max_length=200)
    secret: str | None = Field(default=None, max_length=4096)
    clear_secret: StrictBool = False
    enabled: StrictBool | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if self.url is not None and public_url(self.url) is None:
            raise ValueError("HTTP connectors require one public http(s) URL on port 80 or 443")
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


def connector_dict(row: Connector) -> dict:
    url = (row.config_json or {}).get("url", "")
    return {
        "id": row.id,
        "key": row.key,
        "name": row.name,
        "kind": row.kind,
        "url": url,
        "method": "GET",
        "capabilities": list(row.capabilities),
        "status": row.status,
        "health": row.health,
        "enabled": row.enabled,
        "last_run_id": row.last_run_id,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        **public_secret(row.secret_ref),
    }


def get_connector(session: Session, connector_id: UUID) -> Connector:
    row = session.get(Connector, str(connector_id))
    if row is None:
        raise HTTPException(404, "Connector not found")
    return row


def active_check(session: Session, connector_id: str) -> Run | None:
    for run in session.scalars(
        select(Run).where(Run.executor_type == "http_connector", Run.status.not_in(TERMINAL))
    ):
        if run.parameters.get("connector_id") == connector_id:
            return run
    return None


def apply_secret(row: Connector, *, secret_ref: str | None = None, secret: str | None = None, clear=False):
    if clear:
        clear_secret_file(row.secret_ref)
        row.secret_ref = ""
        return
    if secret:
        clear_secret_file(row.secret_ref)
        row.secret_ref = store_secret_file(row.id, secret.strip())
        return
    if secret_ref is not None:
        if secret_ref != row.secret_ref:
            clear_secret_file(row.secret_ref)
        row.secret_ref = secret_ref


def sync_connector_from_run(session: Session, run: Run, status: str) -> None:
    if run.executor_type != "http_connector":
        return
    connector_id = (run.parameters or {}).get("connector_id")
    row = session.get(Connector, connector_id) if connector_id else None
    if row is None:
        return
    if status == "succeeded":
        row.status, row.health = "ready", "healthy"
    elif status in {"failed", "interrupted"}:
        row.status, row.health = "failed", "unhealthy"
    elif status == "canceled":
        row.status = "ready" if row.health == "healthy" else "unconfigured"
    row.updated_at = utcnow()


@router.get("/kinds")
def kinds():
    return list(KINDS)


@router.get("")
def connectors(session: DB, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    return [
        connector_dict(row)
        for row in session.scalars(
            select(Connector).order_by(Connector.name, Connector.id).limit(limit).offset(offset)
        )
    ]


@router.post("", status_code=201)
def create(body: ConnectorWrite, session: DB):
    spec = kind_spec(body.kind)
    if session.scalar(select(Connector.id).where(Connector.key == body.key).limit(1)):
        raise HTTPException(409, "A connector with this key already exists")
    row = Connector(
        key=body.key,
        name=body.name,
        kind=body.kind,
        status="unconfigured",
        health="unknown",
        capabilities=list(spec["capabilities"]),
        config_json={"url": body.url, "method": "GET"},
        enabled=body.enabled,
    )
    session.add(row)
    session.flush()
    apply_secret(row, secret_ref=body.secret_ref, secret=body.secret)
    session.commit()
    return connector_dict(row)


@router.get("/{connector_id}")
def detail(connector_id: UUID, session: DB):
    return connector_dict(get_connector(session, connector_id))


@router.patch("/{connector_id}")
def edit(connector_id: UUID, body: ConnectorPatch, session: DB):
    row = get_connector(session, connector_id)
    if active_check(session, row.id):
        raise HTTPException(409, "Cancel or finish the health check before editing this connector")
    if body.name is not None:
        row.name = body.name
    if body.url is not None:
        row.config_json = {**row.config_json, "url": body.url, "method": "GET"}
    if body.enabled is not None:
        row.enabled = body.enabled
    apply_secret(row, secret_ref=body.secret_ref, secret=body.secret, clear=body.clear_secret)
    row.updated_at = utcnow()
    session.commit()
    return connector_dict(row)


@router.delete("/{connector_id}", status_code=204)
def remove(connector_id: UUID, session: DB):
    row = get_connector(session, connector_id)
    if active_check(session, row.id):
        raise HTTPException(409, "Cancel the health check before removing this connector")
    apply_secret(row, clear=True)
    session.delete(row)
    session.commit()


@router.post("/{connector_id}/check", status_code=202)
def check(connector_id: UUID, session: DB):
    row = get_connector(session, connector_id)
    kind_spec(row.kind)
    if not row.enabled:
        raise HTTPException(409, "Enable the connector before checking it")
    url = public_url((row.config_json or {}).get("url"))
    if url is None:
        raise HTTPException(422, "HTTP connectors require one public http(s) URL on port 80 or 443")
    if row.secret_ref:
        try:
            authorization_headers(row.secret_ref, required=True)
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from exc
    if active_check(session, row.id):
        raise HTTPException(409, "This connector already has an active health check")
    task = create_task(
        session,
        title=f"Check {row.name}",
        prompt=f"GET {url}",
        capability="connector.http.get",
    )
    run = create_run(
        session,
        task,
        run_type="connector",
        capability="connector.http.get",
        executor_type="http_connector",
        execution_target="container",
        parameters={
            "connector_id": row.id,
            "kind": row.kind,
            "url": url,
            "method": "GET",
            "secret_ref": row.secret_ref,
        },
        permissions=["network_read"],
        retry_class="inspect",
        triggered_by="user",
    )
    row.status = "checking"
    row.last_run_id = run.id
    row.updated_at = utcnow()
    session.commit()
    return run_dict(run)


class HttpConnectorExecutor:
    name = "http_connector"

    def execute(self, session, run):
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        try:
            result = asyncio.run(_check(session, run))
            if result is None:
                session.refresh(run)
                if run.status == "cancel_requested":
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return "done"
            run.metadata_json = {**run.metadata_json, "http_get": result}
            run.summary = f"GET {result.get('url')} returned {result.get('status')}."
            transition(
                session,
                run,
                RunStatus.SUCCEEDED,
                event_type="run.completed",
                payload={"url": result.get("url")},
            )
            session.commit()
        except Exception as exc:
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            else:
                mark_failed(session, run, type(exc).__name__, str(exc) or "HTTP connector check failed")
        return "done"


async def _check(session, run):
    if "network_read" not in run.effective_permissions:
        raise ProviderError("HTTP connectors require explicit network permission")
    url = public_url((run.parameters or {}).get("url"))
    if url is None:
        raise ProviderError("HTTP connectors require one public http(s) URL on port 80 or 443")
    extra = {}
    secret_ref = (run.parameters or {}).get("secret_ref") or ""
    if secret_ref:
        extra = authorization_headers(secret_ref, required=True)
    append_event(
        session, run.id, "connector.requested", {"kind": "http", "url": url, "used_secret": bool(secret_ref)}
    )
    session.commit()
    pending = asyncio.create_task(fetch_public(url, extra_headers=extra))
    try:
        while True:
            session.refresh(run)
            canceled = run.status == "cancel_requested"
            session.commit()
            if canceled:
                append_event(session, run.id, "connector.canceled", {"kind": "http"})
                return None
            ready, _ = await asyncio.wait([pending], timeout=0.2)
            if ready:
                page = pending.result()
                break
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
    result = {
        "url": page["url"],
        "status": page["status"],
        "content_type": page.get("content_type", ""),
        "text": page.get("text", ""),
        "truncated": bool(page.get("truncated")),
        "untrusted": True,
        "used_secret": bool(secret_ref),
        "checked_at": utcnow().isoformat(),
    }
    if page.get("error"):
        raise ProviderError(page["error"])
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
        json.dump(result, handle)
        handle.flush()
        artifact = register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="http-connector.json",
            run_id=run.id,
            metadata={"connector": True, "kind": "http"},
        )
    result = {**result, "artifact_id": artifact.id}
    append_event(
        session,
        run.id,
        "connector.completed",
        {
            "kind": "http",
            "status": result["status"],
            "artifact_id": artifact.id,
            "used_secret": bool(secret_ref),
        },
    )
    session.commit()
    return result
