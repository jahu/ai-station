"""Fixed market-data endpoints, saved credentials and bounded inspectable account reads."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
import time
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.events import append_event
from app.http_fetch import fetch_public
from app.models import Connector
from app.permissions import require
from app.providers import ProviderError
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.secrets import resolve_secret
from app.state import TERMINAL, RunStatus
from app.stock_quotes import (
    StockQuoteError,
    normalize_finnhub_quote,
    normalize_finnhub_search,
    normalize_finnhub_status,
    source_url,
)

router = APIRouter(prefix="/api/market-feeds", tags=["market data"])
DB = Annotated[Session, Depends(session_scope)]


class MarketFeedError(ValueError):
    """Only bounded static diagnostics may cross this boundary."""


def credential(value):
    if not isinstance(value, str) or not re.fullmatch(r"[!-~]{8,512}", value):
        raise MarketFeedError(
            "Configure a valid stock-data credential without whitespace or control characters"
        )
    return value


def connector_revision(row):
    # A key rotated outside the UI (e.g. environment or secret file) also changes
    # the reviewed scope. Only its hash is used and no credential enters the DB.
    try:
        secret_hash = hashlib.sha256(credential(resolve_secret(row.secret_ref)).encode()).hexdigest()
    except (ValueError, OSError, ProviderError):
        secret_hash = None
    return _revision(row, secret_hash)


def _revision(row, secret_hash):
    return hashlib.sha256(
        json.dumps(
            {
                "provider": row.config_json.get("provider"),
                "kind": row.kind,
                "secret_ref": row.secret_ref,
                "secret_hash": secret_hash,
                "enabled": row.enabled,
                "revision": row.config_json.get("market_policy_revision") or row.created_at.isoformat(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def rotate_connector_revision(row):
    row.config_json = {**row.config_json, "market_policy_revision": str(uuid4())}


def reviewed_connector(session, connector_id, revision=None):
    row = session.get(Connector, str(connector_id))
    if (
        row is None
        or row.kind != "market_data"
        or not row.enabled
        or row.config_json.get("provider") != "finnhub"
    ):
        raise MarketFeedError("Choose an enabled Finnhub stock-data account")
    try:
        key = credential(resolve_secret(row.secret_ref))
    except Exception as exc:
        raise MarketFeedError("Configure the saved stock-data credential before continuing") from exc
    if revision is not None and connector_revision(row) != revision:
        raise MarketFeedError("Stock-data account changed; review and select it again")
    return row, key


def validate_stock_scope(session, scope):
    if scope is None or scope.provider != "finnhub":
        return
    if scope.feed is None or not scope.instruments:
        raise MarketFeedError("Review a stock-data account and select 1 to 3 stock symbols")
    reviewed_connector(session, scope.feed.connector_id, scope.feed.connector_revision)


def stock_permissions(scope):
    return ["market_data_read"] if scope is not None and scope.provider == "finnhub" else []


def stock_readiness(session, value):
    if not value or value.get("provider") != "finnhub":
        return None
    from app.market_schema import MarketScope

    try:
        validate_stock_scope(session, MarketScope.model_validate(value))
    except ValueError:
        return {
            "ready": False,
            "reason": "Review and save the stock-data account and symbols before enabling.",
        }
    return {"ready": True, "reason": None}


class Lookup(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    connector_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    query: str = Field(min_length=1, max_length=80)

    @field_validator("query")
    @classmethod
    def valid_query(cls, value):
        source_url("search", value)
        return value


class FeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: UUID
    connector_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Literal["check", "search"]
    query: str | None = None
    deadline_at: str


@router.post("/{connector_id}/search", status_code=202)
def search(connector_id: UUID, body: Lookup, session: DB):
    try:
        row, _ = reviewed_connector(session, connector_id, body.connector_revision)
        return enqueue(session, row, "search", query=body.query)
    except MarketFeedError as exc:
        raise HTTPException(409, str(exc)) from exc


def enqueue(session, row, operation, *, query=None):
    from app.connectors import active_check

    try:
        reviewed_connector(session, row.id)
    except MarketFeedError as exc:
        raise HTTPException(409, str(exc)) from exc
    if active_check(session, row.id):
        raise HTTPException(409, "Finish or stop the current stock-data operation first")
    task = create_task(
        session,
        title="Check stock-data account" if operation == "check" else "Find a stock symbol",
        prompt="Read the reviewed Finnhub endpoint; do not infer prices or account entitlements.",
        capability="connector.market.read",
    )
    request = FeedRequest(
        connector_id=row.id,
        connector_revision=connector_revision(row),
        operation=operation,
        query=query,
        deadline_at=(utcnow() + timedelta(seconds=60)).isoformat(),
    )
    run = create_run(
        session,
        task,
        run_type="connector",
        capability="connector.market.read",
        executor_type="market_feed",
        execution_target="container",
        parameters=request.model_dump(mode="json"),
        permissions=["network_read", "market_data_read"],
        retry_class="inspect",
        triggered_by="user",
    )
    if operation == "check":
        row.status, row.last_run_id = "checking", run.id
        row.updated_at = utcnow()
    session.commit()
    return run_dict(run)


def safe_result(value, key):
    if isinstance(value, str) and key in value:
        raise MarketFeedError("Stock-data provider returned a credential-bearing response; nothing was saved")
    if isinstance(value, dict):
        for name, item in value.items():
            safe_result(name, key)
            safe_result(item, key)
    if isinstance(value, list):
        for item in value:
            safe_result(item, key)
    return value


async def read_page(session, run, connector_id, revision, operation, *, symbol=None, deadline):
    """Used by health, lookup and the ordinary market quote stage, never by handlers."""
    require(run.effective_permissions, "network_read")
    require(run.effective_permissions, "market_data_read")
    _, key = reviewed_connector(session, connector_id, revision)
    url = source_url(operation, symbol)
    safe_result(url, key)
    append_event(
        session, run.id, "market.requested", {"provider": "finnhub", "operation": operation, "url": url}
    )
    session.commit()
    pending = None
    try:
        pending = asyncio.create_task(fetch_public(url, extra_headers={"X-Finnhub-Token": key}))
        while True:
            session.refresh(run)
            canceled = run.status == "cancel_requested"
            owned = run.status == "running"
            session.commit()
            if canceled:
                return None
            if not owned:
                raise MarketFeedError(
                    "Stock-data read lost its active Run; inspect before requesting another read"
                )
            if time.monotonic() >= deadline:
                raise MarketFeedError("Stock-data read exceeded its runtime limit")
            ready, _ = await asyncio.wait([pending], timeout=min(0.2, deadline - time.monotonic()))
            if ready:
                page = pending.result()
                break
        # Even if the HTTP future completed, Stop and the current credential
        # revision win before publication; no response body is ever logged.
        session.refresh(run)
        if run.status == "cancel_requested":
            return None
        if run.status != "running":
            raise MarketFeedError(
                "Stock-data read lost its active Run; inspect before requesting another read"
            )
        _, current_key = reviewed_connector(session, connector_id, revision)
        if current_key != key:
            raise MarketFeedError("Stock-data credential changed during the read; review the account")
        safe_result(page, key)
        if page.get("error"):
            raise MarketFeedError("Stock-data endpoint could not be read safely")
        if page.get("status") in {401, 403}:
            raise MarketFeedError(
                "Stock-data account rejected this read; check the credential and subscription"
            )
        if page.get("status") == 429:
            raise MarketFeedError("Stock-data account rate limit reached; no automatic retry was made")
        return page
    except MarketFeedError:
        raise
    except Exception as exc:
        raise MarketFeedError("Stock-data endpoint could not be read safely") from exc
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending


def record_result(session, run, result, *, filename="stock-data.json"):
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
        json.dump(result, handle, ensure_ascii=False, default=str)
        handle.flush()
        artifact = register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename=filename,
            run_id=run.id,
            metadata={"provider": "finnhub", "canonical": True},
        )
    return artifact.id


async def read_stock_quotes(session, run, scope, deadline):
    validate_stock_scope(session, scope)
    status = await read_page(
        session, run, scope.feed.connector_id, scope.feed.connector_revision, "status", deadline=deadline
    )
    if status is None:
        return None
    quotes = []
    for symbol in scope.instruments:
        pages = []
        for operation in ("quote", "profile"):
            page = await read_page(
                session,
                run,
                scope.feed.connector_id,
                scope.feed.connector_revision,
                operation,
                symbol=symbol,
                deadline=deadline,
            )
            if page is None:
                return None
            pages.append(page)
        quote = normalize_finnhub_quote(*pages, status, symbol, now=utcnow())
        quotes.append(
            {
                "instrument": symbol,
                "price": quote["price"],
                "source_at": quote["source_at"],
                # The existing DB sequence column is not a trade claim: source_metadata
                # explicitly records that Finnhub only supplied a provider quote time.
                "trade_id": quote["source_sequence"],
                "source_url": quote["source_url"],
                "source_metadata": {
                    **quote["metadata"],
                    "connector_id": str(scope.feed.connector_id),
                    "connector_revision": scope.feed.connector_revision,
                },
            }
        )
    _, key = reviewed_connector(session, scope.feed.connector_id, scope.feed.connector_revision)
    result = {"provider": "finnhub", "quotes": quotes, "fetched_at": utcnow().isoformat()}
    safe_result(result, key)
    artifact_id = record_result(session, run, result, filename="stock-quotes.json")
    return {"quotes": quotes, "artifact_id": artifact_id}


class MarketFeedExecutor:
    name = "market_feed"

    def execute(self, session, run):
        try:
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return "done"
            require(run.effective_permissions, "network_read")
            require(run.effective_permissions, "market_data_read")
            request = FeedRequest.model_validate(run.parameters)
            from datetime import datetime

            remaining = (datetime.fromisoformat(request.deadline_at) - utcnow()).total_seconds()
            if not 0 < remaining <= 60:
                raise MarketFeedError("Stock-data read expired; request a new operation")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            operation = "status" if request.operation == "check" else "search"
            page = asyncio.run(
                read_page(
                    session,
                    run,
                    request.connector_id,
                    request.connector_revision,
                    operation,
                    symbol=request.query,
                    deadline=time.monotonic() + remaining,
                )
            )
            if page is None:
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                return "done"
            parsed = (
                normalize_finnhub_status(page, now=utcnow())
                if operation == "status"
                else normalize_finnhub_search(page, request.query)
            )
            result = {
                "provider": "finnhub",
                "operation": request.operation,
                "source_url": page["url"],
                "fetched_at": utcnow().isoformat(),
                **parsed,
            }
            _, key = reviewed_connector(session, request.connector_id, request.connector_revision)
            safe_result(result, key)
            artifact_id = record_result(session, run, result)
            run.metadata_json = {**run.metadata_json, "market_feed": {**result, "artifact_id": artifact_id}}
            run.summary = (
                "Read the US market-status endpoint; symbol quote entitlements were not tested."
                if operation == "status"
                else f"Found {len(parsed['symbols'])} matching stock symbols."
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            session.commit()
        except Exception as exc:
            session.rollback()
            session.refresh(run)
            if run.status in TERMINAL:
                return "done"
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            else:
                reason = (
                    str(exc)
                    if isinstance(exc, (MarketFeedError, StockQuoteError))
                    else "Stock-data read failed; review its account and permission scope"
                )
                mark_failed(session, run, "StockDataReadFailed", reason)
            session.commit()
        return "done"
