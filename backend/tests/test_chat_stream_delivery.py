"""Account-scoped streamed delivery must not serialize a DB transaction per token."""

import asyncio
import time

from app.chat_reasoning import CompletionFinished, ReasoningDelta
from app.db import control_session_factory, get_engine
from app.engine import tick
from app.local_provider import LocalChatProvider
from sqlalchemy import event
from test_account_private_api import accounts, private_app  # noqa: F401


def test_fast_stream_persists_ordered_private_output_with_bounded_transactions(
    accounts,  # noqa: F811
    monkeypatch,
    record_property,
):
    _, alice, bob = accounts
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["fixture-model"])
    closed = []

    async def stream(self, **params):
        try:
            for _ in range(64):
                yield ReasoningDelta("myśl ")
            for _ in range(400):
                yield "żółw "
            yield CompletionFinished("stop")
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = alice.post("/api/chat/conversations", json={"model": "fixture-model"})
    assert response.status_code == 201, response.text
    conversation = response.json()["id"]
    response = alice.post(
        f"/api/chat/conversations/{conversation}/messages",
        json={"content": "Synthetic stream", "web_search": {"enabled": False}},
    )
    assert response.status_code == 202, response.text
    run = response.json()["id"]
    transactions = []

    def began(connection):
        transactions.append(1)

    engine = get_engine()
    event.listen(engine, "begin", began)
    started = time.monotonic()
    try:
        with control_session_factory()() as queue:
            assert tick(queue, "delivery-performance") == run
    finally:
        event.remove(engine, "begin", began)
    elapsed = time.monotonic() - started
    record_property("sqlite_transactions", len(transactions))
    record_property("delivery_seconds", elapsed)
    record_property("provider_chunks", 464)
    result = alice.get(f"/api/chat/conversations/{conversation}").json()["messages"][-1]
    assert result["content"] == "żółw " * 400
    assert result["metadata"]["reasoning_text"] == "myśl " * 64
    assert result["metadata"]["partial"] is False and closed == [True]
    events = alice.get(f"/api/runs/{run}/events").json()
    assert (
        "".join(e["payload"]["text"] for e in events if e["event_type"] == "chat.delta") == result["content"]
    )
    assert (
        "".join(e["payload"]["text"] for e in events if e["event_type"] == "chat.reasoning_delta")
        == result["metadata"]["reasoning_text"]
    )
    assert bob.get(f"/api/runs/{run}/events").status_code == 404
    assert len(transactions) < 60, f"{len(transactions)} transactions for 464 chunks in {elapsed:.2f}s"


def test_buffered_text_becomes_durable_while_provider_waits_and_stop_preserves_it(accounts, monkeypatch):  # noqa: F811
    from app.models import Message, Run
    from app.runs import request_cancel
    from sqlalchemy import select

    _, alice, _ = accounts
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["fixture-model"])
    closed = []

    async def stream(self, **params):
        try:
            yield "First. "
            yield "Buffered. "
            await asyncio.sleep(0.2)
            # A second writer must remain usable while inference is silent.
            with control_session_factory()() as other:
                message = other.scalar(
                    select(Message).where(Message.run_id == run, Message.role == "assistant")
                )
                assert message.content == "First. Buffered. "
                request_cancel(other, other.get(Run, run))
                other.commit()
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    conversation = alice.post("/api/chat/conversations", json={"model": "fixture-model"}).json()["id"]
    response = alice.post(
        f"/api/chat/conversations/{conversation}/messages",
        json={"content": "Synthetic cancellation", "web_search": {"enabled": False}},
    )
    assert response.status_code == 202, response.text
    run = response.json()["id"]
    with control_session_factory()() as queue:
        assert tick(queue, "delivery-cancellation") == run
    answer = alice.get(f"/api/chat/conversations/{conversation}").json()["messages"][-1]
    assert answer["content"] == "First. Buffered. " and answer["metadata"]["partial"] is True
    assert alice.get(f"/api/runs/{run}").json()["status"] == "canceled" and closed == [True]


def test_provider_failure_flushes_received_buffer_and_keeps_partial_answer(accounts, monkeypatch):  # noqa: F811
    from app.providers import ProviderError

    _, alice, _ = accounts
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["fixture-model"])
    closed = []

    async def stream(self, **params):
        try:
            yield "First. "
            yield "Received before failure."
            raise ProviderError("Synthetic interrupted provider")
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    conversation = alice.post("/api/chat/conversations", json={"model": "fixture-model"}).json()["id"]
    response = alice.post(
        f"/api/chat/conversations/{conversation}/messages",
        json={"content": "Synthetic provider failure", "web_search": {"enabled": False}},
    )
    assert response.status_code == 202, response.text
    run = response.json()["id"]
    with control_session_factory()() as queue:
        assert tick(queue, "delivery-provider-failure") == run
    answer = alice.get(f"/api/chat/conversations/{conversation}").json()["messages"][-1]
    assert answer["content"] == "First. Received before failure."
    assert answer["metadata"]["partial"] is True and closed == [True]
    assert alice.get(f"/api/runs/{run}").json()["status"] == "failed"
