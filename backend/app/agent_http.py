"""A reviewed saved GET source; credentials never become model arguments/context."""

import asyncio
import hashlib
import json
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import quote, quote_plus

from app.artifacts import register_file
from app.db import utcnow
from app.events import append_event
from app.http_fetch import fetch_public, public_url
from app.models import Artifact, Connector
from app.permissions import require
from app.providers import ProviderError
from app.python_execution import read_owned_file
from app.secrets import authorization_headers, secret_present


def connector_revision(row):
    policy = {
        "id": row.id,
        "kind": row.kind,
        "url": (row.config_json or {}).get("url"),
        "method": "GET",
        "secret_ref": row.secret_ref or "",
        "enabled": row.enabled,
        "version": (row.config_json or {}).get("http_policy_version", "legacy"),
    }
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def reviewed_connector(session, scope):
    if scope is None:
        raise ValueError("Choose and review a saved HTTP connection before activation")
    row = session.get(Connector, str(scope.connector_id), populate_existing=True)
    if row is None or row.kind != "http" or not row.enabled:
        raise ValueError("The reviewed HTTP connection is unavailable; select a connection again")
    url = public_url((row.config_json or {}).get("url"))
    if url is None or connector_revision(row) != scope.connector_revision:
        raise ValueError("HTTP connection changed; review and select it again")
    if row.secret_ref and not url.startswith("https://"):
        raise ValueError("Authenticated HTTP connections require HTTPS")
    if row.secret_ref and not secret_present(row.secret_ref):
        raise ValueError("The saved HTTP credential is missing; update the connection")
    return row


def scrub_response(value, headers):
    """Scrub exact sent credentials, including common JSON/URL encodings of echoes."""
    auth = headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ")
    secrets = set()
    for raw in (auth, token):
        if raw:
            secrets.update((raw, quote(raw, safe=""), quote_plus(raw), json.dumps(raw)[1:-1]))

    def scrub(item):
        if isinstance(item, str):
            for secret in sorted(secrets, key=len, reverse=True):
                item = item.replace(secret, "[redacted]")
            return item
        if isinstance(item, list):
            return [scrub(child) for child in item]
        if isinstance(item, dict):
            return {scrub(key): scrub(child) for key, child in item.items()}
        return item

    return scrub(value)


async def read_response(session, run, url, secret_ref, *, deadline=None, validate=None):
    """Use the shared public transport and poll Stop/scope/deadline until adoption."""
    require(run.effective_permissions, "network_read")
    if secret_ref and not url.startswith("https://"):
        raise ProviderError("Authenticated HTTP connections require HTTPS")
    try:
        headers = authorization_headers(secret_ref, required=True) if secret_ref else {}
    except Exception:
        raise ProviderError("The configured HTTP credential is unavailable") from None
    if validate:
        validate()
    end = min(deadline or float("inf"), time.monotonic() + 25)
    pending = None
    try:
        while True:
            session.refresh(run)
            if run.status == "cancel_requested":
                return None
            if time.monotonic() >= end:
                raise ProviderError("HTTP connection runtime limit exceeded")
            if validate:
                validate()
            session.commit()
            if pending is None:
                pending = asyncio.create_task(fetch_public(url, extra_headers=headers))
            ready, _ = await asyncio.wait([pending], timeout=0.1)
            if ready:
                try:
                    page = scrub_response(pending.result(), headers)
                except Exception:
                    raise ProviderError("The reviewed HTTP request failed") from None
                session.refresh(run)
                if run.status == "cancel_requested":
                    return None
                if time.monotonic() >= end:
                    raise ProviderError("HTTP connection runtime limit exceeded")
                if validate:
                    validate()
                if page.get("error"):
                    # Transport errors can contain arbitrary credential echoes as well.
                    raise ProviderError("The reviewed HTTP request failed")
                return page
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending


async def execute_source(session, run, scope, deadline):
    require(run.effective_permissions, "http_connector_read")
    row = reviewed_connector(session, scope)
    url = row.config_json["url"]
    append_event(session, run.id, "tool.started", {"tool": "http_connector", "connector_id": row.id})
    session.commit()
    page = await read_response(
        session,
        run,
        url,
        row.secret_ref,
        deadline=deadline,
        validate=lambda: reviewed_connector(session, scope),
    )
    if page is None:
        return None
    if page.get("status") != 200 or not isinstance(page.get("text"), str) or not page["text"].strip():
        raise ProviderError("The reviewed HTTP connection did not return readable data (HTTP 200 required)")
    result = {
        "connector_id": str(scope.connector_id),
        "connector_revision": scope.connector_revision,
        "urls": [url],
        "pages": [page],
        "used_secret": bool(row.secret_ref),
        "fetched_at": utcnow().isoformat(),
        "untrusted": True,
    }
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
        json.dump(result, handle)
        handle.flush()
        artifact = register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="connected-api.json",
            run_id=run.id,
            metadata={"tool": "http_connector", "connector_id": str(scope.connector_id)},
        )
    append_event(session, run.id, "tool.completed", {"tool": "http_connector", "artifact_id": artifact.id})
    session.commit()
    return {**result, "artifact_id": artifact.id}


def verified_result(session, source, scope, *, for_execution=True):
    """Exact owned capture, usable historically even after the live connector changes."""
    if scope is None:
        raise ValueError("HTTP capture has no reviewed connection scope")
    if for_execution:
        reviewed_connector(session, scope)
    require(source.effective_permissions, "http_connector_read")
    result = source.metadata_json.get("observation")
    artifact = session.get(Artifact, result.get("artifact_id", "")) if isinstance(result, dict) else None
    if (
        artifact is None
        or artifact.run_id != source.id
        or artifact.artifact_type != "json"
        or artifact.mime_type != "application/json"
        or artifact.trashed_at is not None
        or artifact.metadata_json.get("tool") != "http_connector"
    ):
        raise ValueError("HTTP capture is missing its original source artifact")
    path = read_owned_file(artifact.relative_path, artifact.size_bytes, artifact.sha256, limit=1000000)
    data = json.loads(path.read_bytes())
    urls = data.get("urls")
    pages = data.get("pages")
    if (
        {**data, "artifact_id": artifact.id} != result
        or data.get("connector_id") != str(scope.connector_id)
        or data.get("connector_revision") != scope.connector_revision
        or not isinstance(urls, list)
        or len(urls) != 1
        or not public_url(urls[0])
        or not isinstance(pages, list)
        or len(pages) != 1
        or pages[0].get("status") != 200
        or not isinstance(pages[0].get("text"), str)
        or not pages[0]["text"].strip()
        or data.get("untrusted") is not True
    ):
        raise ValueError("HTTP capture differs from its reviewed source")
    if for_execution and reviewed_connector(session, scope).config_json["url"] != urls[0]:
        raise ValueError("HTTP capture changed its reviewed address")
    return result
