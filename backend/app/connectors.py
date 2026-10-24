"""Named HTTP GET connectors with secret references and inspectable health Runs."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.email_schema import SMTPSettings
from app.events import append_event
from app.github_connector import repository_name
from app.http_fetch import public_url
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
        "operational": True,
        "capabilities": ["github.read"],
        "summary": "Read repository details, open issues and PRs through the existing host gh session.",
    },
    {
        "kind": "email",
        "operational": True,
        "capabilities": ["email.check", "email.preview", "email.send"],
        "summary": "TLS SMTP with reviewed recipients, message previews, approval and durable delivery receipts.",
    },
    {
        "kind": "market_data",
        "operational": True,
        "capabilities": ["market.check", "market.search", "market.quote"],
        "summary": "Finnhub US stock data through a saved account; endpoint checks do not prove symbol entitlements.",
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
    kind: Literal["http", "github", "email", "market_data"] = "http"
    market_provider: Literal["finnhub"] | None = None
    url: str = Field(default="", max_length=2000)
    repository: str = Field(default="", max_length=140)
    smtp: SMTPSettings | None = None
    secret_ref: str = Field(default="", max_length=200)
    secret: str | None = Field(default=None, max_length=4096)
    enabled: StrictBool = True

    @model_validator(mode="after")
    def validate_connector(self):
        if not _KEY.fullmatch(self.key):
            raise ValueError("Choose a unique lowercase connector key")
        if self.kind != "market_data" and self.market_provider is not None:
            raise ValueError("Market provider belongs only to market data connectors")
        if self.kind == "email":
            if self.smtp is None or self.url or self.repository:
                raise ValueError("Email requires SMTP configuration, without HTTP URL or repository")
            if bool(self.smtp.username) != bool(self.secret or self.secret_ref):
                raise ValueError("SMTP username and credential must be configured together")
        elif self.smtp is not None:
            raise ValueError("SMTP configuration belongs only to email connectors")
        elif self.kind == "market_data":
            if self.market_provider != "finnhub" or self.url or self.repository:
                raise ValueError("Choose Finnhub without a custom URL or repository")
            if self.secret is not None:
                from app.market_feeds import credential

                credential(self.secret)
        elif self.kind == "github":
            self.repository = repository_name(self.repository)
            if self.url or self.secret or self.secret_ref:
                raise ValueError("GitHub uses the host gh session; do not provide URLs or secrets")
        elif public_url(self.url) is None or self.repository:
            raise ValueError("HTTP connectors require one public http(s) URL on port 80 or 443")
        try:
            self.secret_ref = parse_secret_ref(self.secret_ref)
        except (ValueError, PathBoundaryError) as exc:
            raise ValueError(str(exc)) from exc
        if self.secret is not None and not self.secret.strip():
            raise ValueError("A stored secret cannot be empty")
        return self


class ConnectorPatch(BaseModel):
    expected_updated_at: datetime | None = None
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    smtp: SMTPSettings | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    repository: str | None = Field(default=None, max_length=140)
    secret_ref: str | None = Field(default=None, max_length=200)
    secret: str | None = Field(default=None, max_length=4096)
    clear_secret: StrictBool = False
    enabled: StrictBool | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if self.repository is not None:
            self.repository = repository_name(self.repository)
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


def http_policy_revision(row):
    from app.agent_http import connector_revision

    return connector_revision(row)


def email_policy_revision(row):
    from app.market_email import connector_revision

    return connector_revision(row)


def connector_dict(row: Connector) -> dict:
    url = (row.config_json or {}).get("url", "")
    return {
        "id": row.id,
        "key": row.key,
        "name": row.name,
        "kind": row.kind,
        "url": url,
        "repository": row.config_json.get("repository", ""),
        "method": "SMTP" if row.kind == "email" else "GET",
        **(
            {"smtp": row.config_json.get("smtp"), "email_policy_revision": email_policy_revision(row)}
            if row.kind == "email"
            else {}
        ),
        **({"http_policy_revision": http_policy_revision(row)} if row.kind == "http" else {}),
        **market_feed_public(row),
        "capabilities": list(row.capabilities),
        "status": row.status,
        "health": row.health,
        "enabled": row.enabled,
        "last_run_id": row.last_run_id,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        **public_secret(row.secret_ref),
    }


def market_feed_public(row):
    if row.kind != "market_data":
        return {}
    from app.market_feeds import connector_revision

    return {
        "market_provider": row.config_json.get("provider"),
        "market_policy_revision": connector_revision(row),
    }


def get_connector(session: Session, connector_id: UUID) -> Connector:
    row = session.get(Connector, str(connector_id))
    if row is None:
        raise HTTPException(404, "Connector not found")
    return row


def active_check(session: Session, connector_id: str, *, excluding: str | None = None) -> Run | None:
    for run in session.scalars(
        select(Run).where(
            Run.executor_type.in_(
                [
                    "http_connector",
                    "github_read",
                    "email_send",
                    "email_check",
                    "market_feed",
                    "agent_market",
                    "agent_workflow",
                ]
            ),
            Run.status.not_in(TERMINAL),
        )
    ):
        market = (run.parameters.get("definition") or {}).get("market") or {}
        feed = market.get("feed") or {}
        if (
            run.id != excluding
            and run.status not in TERMINAL
            and (
                run.parameters.get("connector_id") == connector_id or feed.get("connector_id") == connector_id
            )
        ):
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
    if run.executor_type not in {"http_connector", "github_read", "email_check", "market_feed"}:
        return
    if run.executor_type == "market_feed" and run.parameters.get("operation") != "check":
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
    other = active_check(session, row.id, excluding=run.id)
    if other and (
        row.kind != "market_data"
        or other.executor_type == "market_feed"
        and other.parameters.get("operation") == "check"
    ):
        row.status = "checking"
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
        config_json={"smtp": body.smtp.model_dump()}
        if body.kind == "email"
        else {"provider": body.market_provider}
        if body.kind == "market_data"
        else {"repository": body.repository}
        if body.kind == "github"
        else {"url": body.url, "method": "GET"},
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
        raise HTTPException(409, "Cancel or finish the connector operation before editing this connector")
    if row.kind in {"email", "market_data"} and body.expected_updated_at != row.updated_at:
        raise HTTPException(409, "Connector settings changed; refresh and review before saving")
    if row.kind == "market_data":
        if body.url is not None or body.repository is not None or body.smtp is not None:
            raise HTTPException(422, "Stock data does not accept custom URLs, repositories or SMTP")
        if body.secret is not None:
            from app.market_feeds import credential

            try:
                credential(body.secret)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
    if body.smtp is not None:
        if row.kind != "email":
            raise HTTPException(422, "SMTP configuration belongs only to email connectors")
        row.config_json = {"smtp": body.smtp.model_dump()}
        row.status, row.health = "unconfigured", "unknown"
    if row.kind == "email" and any(value is not None for value in (body.url, body.repository)):
        raise HTTPException(422, "Email does not accept HTTP URLs or repositories")
    if row.kind == "github" and any(value is not None for value in (body.url, body.secret, body.secret_ref)):
        raise HTTPException(422, "GitHub uses the host gh session; do not provide URLs or secrets")
    if body.repository is not None:
        if row.kind != "github":
            raise HTTPException(422, "Repository applies only to GitHub connectors")
        row.config_json = {"repository": body.repository}
        row.last_run_id, row.status, row.health = None, "unconfigured", "unknown"
    if body.name is not None:
        row.name = body.name
    if body.url is not None:
        row.config_json = {**row.config_json, "url": body.url, "method": "GET"}
    if body.enabled is not None:
        row.enabled = body.enabled
    if row.kind == "email":
        config = SMTPSettings.model_validate(row.config_json["smtp"])
        has_secret = (
            bool(body.secret or (body.secret_ref if body.secret_ref is not None else row.secret_ref))
            and not body.clear_secret
        )
        if bool(config.username) != has_secret:
            raise HTTPException(422, "SMTP username and credential must be configured together")
    if row.kind == "email" and (body.secret is not None or body.secret_ref is not None or body.clear_secret):
        row.status, row.health, row.last_run_id = "unconfigured", "unknown", None
    if row.kind == "email" and (
        body.smtp is not None
        or body.secret is not None
        or body.secret_ref is not None
        or body.clear_secret
        or body.enabled is not None
    ):
        from app.market_email import rotate_connector_revision

        rotate_connector_revision(row)
    if row.kind == "market_data" and (
        body.secret is not None
        or body.secret_ref is not None
        or body.clear_secret
        or body.enabled is not None
    ):
        from app.market_feeds import rotate_connector_revision

        rotate_connector_revision(row)
        row.status, row.health, row.last_run_id = "unconfigured", "unknown", None
    if row.kind == "http" and (
        body.url is not None
        or body.secret is not None
        or body.secret_ref is not None
        or body.clear_secret
        or body.enabled is not None
    ):
        from uuid import uuid4

        row.config_json = {**row.config_json, "http_policy_version": str(uuid4())}
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
    if row.kind == "market_data":
        from app.market_feeds import enqueue

        return enqueue(session, row, "check")
    if row.kind == "email":
        from app.email_delivery import enqueue_check

        return enqueue_check(session, row)
    if row.kind == "github":
        from app.github_connector import enqueue

        return enqueue(session, row)
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
            "http_scope": {"connector_id": row.id, "connector_revision": http_policy_revision(row)},
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
    from app.agent_http import read_response, reviewed_connector
    from app.agent_schema import AgentHttpScope

    secret_ref = (run.parameters or {}).get("secret_ref") or ""
    raw_scope = run.parameters.get("http_scope")
    scope = AgentHttpScope.model_validate(raw_scope) if raw_scope else None
    append_event(
        session, run.id, "connector.requested", {"kind": "http", "url": url, "used_secret": bool(secret_ref)}
    )
    session.commit()
    page = await read_response(
        session,
        run,
        url,
        secret_ref,
        validate=(lambda headers: reviewed_connector(session, scope, headers)) if scope else None,
    )
    if page is None:
        append_event(session, run.id, "connector.canceled", {"kind": "http"})
        return None
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
        raise ProviderError("The reviewed HTTP request failed")
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


@router.get("/{connector_id}/snapshot")
def snapshot(connector_id: UUID, session: DB):
    from app.github_connector import saved_snapshot

    row = get_connector(session, connector_id)
    if row.kind != "github":
        raise HTTPException(422, "Snapshots apply to GitHub connectors")
    latest = session.get(Run, row.last_run_id) if row.last_run_id else None
    error = latest.error_message if latest and latest.parameters.get("connector_id") == row.id else ""
    return {
        "connector": connector_dict(row),
        "snapshot": saved_snapshot(session, row),
        "refresh_error": error,
    }
