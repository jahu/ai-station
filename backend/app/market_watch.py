"""Deterministic market workflows; the model cannot choose prices, thresholds or recipients."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
import time
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from sqlalchemy import select

from app.agent_schema import AgentSettings
from app.artifacts import register_file
from app.db import utcnow
from app.dependencies import depend_on
from app.events import append_event
from app.http_fetch import execute_fetch
from app.market_schema import PAIR_NAMES, MarketScope
from app.models import MarketAlert, MarketObservation, Notice, Run
from app.permissions import require
from app.runs import create_run, mark_failed, transition
from app.state import RunStatus

STEPS = ("market.quote", "market.compare", "market.notify", "market.report")


def policy_key(scope: MarketScope) -> str:
    return hashlib.sha256(
        json.dumps(
            scope.model_dump(mode="json", exclude={"email"}, exclude_none=True), sort_keys=True
        ).encode()
    ).hexdigest()


def source_url(instrument: str) -> str:
    if instrument not in PAIR_NAMES:
        raise ValueError("Unsupported market instrument")
    return f"https://api.exchange.coinbase.com/products/{instrument}/ticker"


def parse_quote(page, instrument, *, now):
    if (
        page.get("url") != source_url(instrument)
        or page.get("status") != 200
        or page.get("content_type") != "application/json"
        or page.get("truncated")
    ):
        raise ValueError("Quote provider returned an unsupported response")
    try:
        data = json.loads(page["text"])
        price, trade_id = data["price"], data["trade_id"]
        if not isinstance(price, str) or not re.fullmatch(r"\d{1,24}(?:\.\d{1,18})?", price):
            raise ValueError("Invalid quote price")
        if (
            Decimal(price) <= 0
            or isinstance(trade_id, bool)
            or not isinstance(trade_id, int)
            or not 0 < trade_id < 10**24
        ):
            raise ValueError("Invalid trade identity or price")
        raw_time = data["time"]
        if not isinstance(raw_time, str) or len(raw_time) > 64:
            raise ValueError("Quote has an invalid source time")
        source_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if source_at.tzinfo is None or not -30 <= (now - source_at).total_seconds() <= 300:
            raise ValueError("Quote is stale or has an invalid source time")
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("Quote provider returned invalid ticker data") from exc
    return {"instrument": instrument, "price": price, "trade_id": str(trade_id), "source_at": source_at}


def publish_market_steps(session, parent, definition):
    from app.market_feeds import stock_permissions, validate_stock_scope

    validate_stock_scope(session, definition.market)
    for permission in stock_permissions(definition.market):
        require(parent.effective_permissions, permission)
    require(parent.effective_permissions, "network_read")
    if definition.market.email is not None:
        require(parent.effective_permissions, "email_send")
        require(parent.effective_permissions, "network_external")
    expected = [{"key": key, "gate": "none"} for key in STEPS]
    if parent.parameters.get("steps") != expected:
        raise ValueError("Market workflow does not match the reviewed deterministic plan")
    children = []
    deadline = (utcnow() + timedelta(seconds=definition.maximum_runtime)).isoformat()
    for key in STEPS:
        child = create_run(
            session,
            parent.task,
            run_type="agent",
            capability="agent.execute" if key == "market.report" else "agent.step",
            executor_type="agent_market",
            execution_target="container",
            parameters={
                "definition": definition.model_dump(mode="json"),
                "tool": key,
                "deadline_at": deadline,
            },
            permissions=["network_read"] + stock_permissions(definition.market)
            if key == "market.quote"
            else (
                ["email_send", "network_external"]
                if key == "market.notify" and definition.market.email is not None
                else []
            ),
            retry_class="inspect",
            triggered_by=parent.triggered_by,
            agent_id=parent.agent_id,
            parent_run_id=parent.id,
        )
        if children:
            depend_on(session, child, children[-1])
        children.append(child)
    append_event(
        session,
        parent.id,
        "workflow.published",
        {"steps": [dict(key=key, run_id=child.id) for key, child in zip(STEPS, children, strict=True)]},
    )
    return children


def sibling_result(session, run, step):
    sibling = session.scalar(
        select(Run)
        .where(Run.parent_run_id == run.parent_run_id, Run.executor_type == "agent_market", Run.id != run.id)
        .filter(Run.parameters["tool"].as_string() == step)
    )
    if (
        sibling is None
        or sibling.status != "succeeded"
        or sibling.agent_id != run.agent_id
        or sibling.task_id != run.task_id
        or sibling.parameters["definition"] != run.parameters["definition"]
        or not isinstance(sibling.metadata_json.get("market_result"), dict)
    ):
        raise ValueError("Market workflow is missing a successful source-bound stage")
    return sibling, sibling.metadata_json["market_result"]


def observe(session, run, definition, deadline):
    require(run.effective_permissions, "network_read")
    scope = definition.market
    if scope.provider == "finnhub":
        from app.market_feeds import read_stock_quotes

        response = asyncio.run(read_stock_quotes(session, run, scope, deadline))
    else:
        response = asyncio.run(
            execute_fetch(session, run, [source_url(pair) for pair in scope.instruments], deadline=deadline)
        )
    if response is None:
        return None
    now = utcnow()
    quotes = (
        response["quotes"]
        if scope.provider == "finnhub"
        else [
            {**parse_quote(page, pair, now=now), "source_url": source_url(pair), "source_metadata": {}}
            for pair, page in zip(scope.instruments, response["pages"], strict=True)
        ]
    )
    key = policy_key(scope)
    ids = []
    for quote in quotes:
        row = session.scalar(
            select(MarketObservation).where(
                MarketObservation.agent_id == run.agent_id,
                MarketObservation.policy_key == key,
                MarketObservation.instrument == quote["instrument"],
                MarketObservation.trade_id == quote["trade_id"],
            )
        )
        if row is not None:
            if Decimal(row.price) != Decimal(quote["price"]) or row.source_at != quote["source_at"]:
                raise ValueError(
                    "Provider changed an already recorded source observation; inspect the source"
                )
        else:
            row = MarketObservation(
                agent_id=run.agent_id,
                run_id=run.id,
                policy_key=key,
                observed_at=now,
                **quote,
            )
            session.add(row)
            session.flush()
        ids.append(row.id)
    return {"observation_ids": ids, "source_artifact_id": response["artifact_id"], "policy_key": key}


def observation_fresh(row, *, now=None):
    now = now or utcnow()
    metadata = row.source_metadata or {}
    if not metadata:
        return -30 <= (now - row.source_at).total_seconds() <= 300
    if (
        metadata.get("provider") != "finnhub"
        or metadata.get("currency") != "USD"
        or metadata.get("source_time_kind") != "provider_quote"
        or metadata.get("freshness") not in {"recent", "last_known"}
        or type(metadata.get("market_open")) is not bool
        or metadata.get("market_session") not in {"regular", "pre-market", "post-market", "closed"}
        or not -30 <= (now - row.observed_at).total_seconds() <= 300
    ):
        return False
    from app.stock_quotes import source_url as stock_url

    if row.source_url != stock_url("quote", row.instrument) or row.trade_id != str(
        int(row.source_at.timestamp())
    ):
        return False
    try:
        status_at = datetime.fromisoformat(metadata["market_status_at"])
        if status_at.tzinfo is None or not -30 <= (now - status_at).total_seconds() <= 300:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    regular = metadata["market_open"] and metadata["market_session"] == "regular"
    return -30 <= (now - row.source_at).total_seconds() <= (300 if regular else 604800)


def compare(session, run, definition):
    source, result = sibling_result(session, run, "market.quote")
    scope = definition.market
    key = policy_key(scope)
    rows = []
    for oid in result["observation_ids"]:
        current = session.get(MarketObservation, oid)
        if (
            current is None
            or current.agent_id != run.agent_id
            or current.policy_key != key
            or current.instrument not in scope.instruments
        ):
            raise ValueError("Quote provenance does not match the reviewed scope")
        item = {
            "observation_id": current.id,
            "instrument": current.instrument,
            "price": current.price,
            "currency": (current.source_metadata or {}).get("currency") or current.instrument.split("-")[1],
            "source_metadata": current.source_metadata or {},
            "source_at": current.source_at.isoformat(),
            "observed_at": current.observed_at.isoformat(),
            "source_url": current.source_url,
            "baseline_id": None,
            "change_percent": None,
            "alert_id": None,
            "status": "baseline",
        }
        previous = session.scalar(
            select(MarketObservation)
            .where(
                MarketObservation.agent_id == run.agent_id,
                MarketObservation.policy_key == key,
                MarketObservation.instrument == current.instrument,
                MarketObservation.id != current.id,
                MarketObservation.run_id != source.id,
            )
            .order_by(MarketObservation.source_at.desc())
            .limit(1)
        )
        if current.run_id != source.id:
            item["status"] = "repeated"
        elif not observation_fresh(current):
            item["status"] = "stale"
        elif previous is not None:
            gap = (current.source_at - previous.source_at).total_seconds()
            if gap <= 0 or int(current.trade_id) <= int(previous.trade_id):
                item["status"] = "out_of_order"
            elif gap > scope.comparison_window_seconds:
                item["status"] = "baseline_expired"
            else:
                item["baseline_id"] = previous.id
                item["baseline_price"] = previous.price
                item["baseline_at"] = previous.source_at.isoformat()
                with localcontext() as context:
                    context.prec = 60
                    change = (
                        (Decimal(current.price) - Decimal(previous.price)) / Decimal(previous.price) * 100
                    )
                    item["change_percent"] = format(change, ".8f")
                crossed = abs(change) >= Decimal(scope.threshold_percent) and (
                    scope.direction == "both"
                    or scope.direction == "up"
                    and change > 0
                    or scope.direction == "down"
                    and change < 0
                )
                item["status"] = "below_threshold"
                if crossed:
                    existing = session.scalar(
                        select(MarketAlert).where(MarketAlert.observation_id == current.id)
                    )
                    last = session.scalar(
                        select(MarketAlert)
                        .join(MarketObservation, MarketAlert.observation_id == MarketObservation.id)
                        .where(
                            MarketObservation.agent_id == run.agent_id,
                            MarketObservation.policy_key == key,
                            MarketObservation.instrument == current.instrument,
                            MarketAlert.observation_id != current.id,
                        )
                        .order_by(MarketAlert.created_at.desc())
                        .limit(1)
                    )
                    if existing:
                        item.update(status="alert", alert_id=existing.id)
                    elif (
                        last is not None
                        and (utcnow() - last.created_at).total_seconds() < scope.cooldown_seconds
                    ):
                        item["status"] = "cooldown"
                    else:
                        alert = MarketAlert(
                            observation_id=current.id,
                            baseline_id=previous.id,
                            run_id=run.id,
                            change_percent=item["change_percent"],
                        )
                        session.add(alert)
                        session.flush()
                        item.update(status="alert", alert_id=alert.id)
        rows.append(item)
    return {
        "rows": rows,
        "policy": scope.model_dump(mode="json"),
        "policy_key": key,
        "quote_run_id": source.id,
    }


def notify(session, run, definition):
    comparison, result = sibling_result(session, run, "market.compare")
    delivered, email_delivery_ids = [], []
    if definition.market.email is not None:
        require(run.effective_permissions, "email_send")
        require(run.effective_permissions, "network_external")
    for item in result["rows"]:
        if not item.get("alert_id"):
            continue
        alert = session.get(MarketAlert, item["alert_id"])
        observation = session.get(MarketObservation, alert.observation_id) if alert else None
        if (
            alert is None
            or alert.run_id != comparison.id
            or observation is None
            or observation.agent_id != run.agent_id
            or observation.policy_key != policy_key(definition.market)
        ):
            raise ValueError("Notification has no matching reviewed comparison")
        if alert.notice_id is None and not observation_fresh(observation):
            item["status"] = "stale_before_delivery"
            continue
        if alert.notice_id is None:
            notice = Notice(
                agent_id=run.agent_id,
                run_id=run.id,
                kind="market_threshold",
                title=f"{item['instrument']} moved {item['change_percent']}%",
                body=f"{item['baseline_price']} → {item['price']} {item['currency']}; compared with the previous valid observation at {item['baseline_at']}. Source: {item['source_url']}. "
                + (
                    "Email submission is recorded separately."
                    if definition.market.email
                    else "In-app alert; no email sent."
                ),
            )
            session.add(notice)
            session.flush()
            alert.notice_id = notice.id
            append_event(
                session,
                run.id,
                "notice.created",
                {"notice_id": notice.id, "kind": notice.kind, "alert_id": alert.id},
            )
        delivered.append(alert.notice_id)
        if definition.market.email is not None:
            from app.market_email import queue_alert

            receipt = queue_alert(session, run, definition, alert.id)
            email_delivery_ids.append(receipt.id)
    return {
        **result,
        "notice_ids": delivered,
        "delivery": "in_app",
        "email_sent": False,
        "email_delivery_ids": email_delivery_ids,
    }


def report(session, run):
    _, result = sibling_result(session, run, "market.notify")
    text = "# Price watch\n\nCompared with the previous valid observation within the reviewed maximum gap.\n\n| Instrument | Price | Change | Outcome |\n| --- | --- | --- | --- |\n"
    for item in result["rows"]:
        text += f"| {item['instrument']} | {item['price']} {item['currency']} | {item['change_percent'] + '%' if item['change_percent'] is not None else '—'} | {item['status'].replace('_', ' ')} |\n"
    text += f"\nIn-app alerts: {len(result['notice_ids'])}.\n\n"
    from app.models import EmailDelivery

    email_receipts = []
    for delivery_id in result.get("email_delivery_ids", []):
        receipt = session.get(EmailDelivery, delivery_id)
        if receipt is None:
            raise ValueError("Missing recorded alert delivery")
        email_receipts.append({"id": receipt.id, "run_id": receipt.run_id, "state": receipt.state})
        text += (
            f"- Email: {receipt.state.replace('_', ' ')}. Delivery `{receipt.id}`; Run `{receipt.run_id}`.\n"
        )
    result = {
        **result,
        "email_receipts": email_receipts,
        "email_sent": any(r["state"] in {"accepted", "accepted_partial"} for r in email_receipts),
    }
    for item in result["rows"]:
        source_kind = (
            "provider quote time"
            if item.get("source_metadata", {}).get("source_time_kind") == "provider_quote"
            else "last-trade time"
        )
        freshness = item.get("source_metadata", {}).get("freshness", "recent")
        text += f"- [{item['instrument']}]({item['source_url']}): {source_kind} {item['source_at']}; {freshness.replace('_', ' ')}; fetched {item['observed_at']}. Observation `{item['observation_id']}`.\n"
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".md") as handle:
        handle.write(text)
        handle.flush()
        register_file(
            session,
            source=Path(handle.name),
            artifact_type="markdown",
            mime_type="text/markdown",
            original_filename="price-watch.md",
            run_id=run.id,
            metadata={"market": True},
        )
    return result


class MarketExecutor:
    name = "agent_market"

    def execute(self, session, run):
        from app.agent_executor import LocalAgentExecutor
        from app.agent_workflow import _remaining_deadline

        if LocalAgentExecutor._canceled(session, run):
            return "done"
        try:
            definition = AgentSettings.model_validate(run.parameters["definition"])
            from app.market_feeds import validate_stock_scope

            validate_stock_scope(session, definition.market)
            parent = session.get(Run, run.parent_run_id)
            step = run.parameters.get("tool")
            if (
                definition.tools != ["market_watch"]
                or parent is None
                or parent.executor_type != "agent_workflow"
                or parent.status != "succeeded"
                or parent.task_id != run.task_id
                or parent.agent_id != run.agent_id
                or parent.parameters.get("definition") != run.parameters["definition"]
                or step not in STEPS
            ):
                raise ValueError("Market stage does not match the frozen agent workflow")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            deadline = _remaining_deadline(run, definition)
            append_event(session, run.id, "tool.started", {"tool": step})
            result = (
                observe(session, run, definition, deadline)
                if step == "market.quote"
                else compare(session, run, definition)
                if step == "market.compare"
                else notify(session, run, definition)
                if step == "market.notify"
                else report(session, run)
            )
            # Keep persistence, threshold receipts and in-app delivery atomic with success.
            session.refresh(run)
            if result is None or run.status == "cancel_requested":
                session.rollback()
                LocalAgentExecutor._canceled(session, run)
                return "done"
            if time.monotonic() >= deadline:
                raise ValueError("Agent runtime limit exceeded during market observation")
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
                json.dump(result, handle)
                handle.flush()
                register_file(
                    session,
                    source=Path(handle.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename=f"{step}.json",
                    run_id=run.id,
                    metadata={"tool": step},
                )
            run.metadata_json = {**run.metadata_json, "market_result": result}
            run.summary = (
                f"{step} completed; {len(result.get('notice_ids', []))} in-app alerts."
                if step == "market.report"
                else f"{step} completed."
            )
            append_event(session, run.id, "tool.completed", {"tool": step})
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            session.commit()
        except Exception as exc:
            session.rollback()
            if not LocalAgentExecutor._canceled(session, run):
                mark_failed(session, run, type(exc).__name__, str(exc) or "Market stage failed")
        return "done"
