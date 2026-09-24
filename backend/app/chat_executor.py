"""Cancellable local completion using the shared Run lifecycle and persisted deltas."""

import asyncio
from contextlib import suppress

from sqlalchemy import select

from app.db import utcnow
from app.events import append_event
from app.local_provider import LocalChatProvider
from app.models import Conversation, Message
from app.providers import ProviderError
from app.runs import mark_failed, transition
from app.state import RunStatus


class ChatExecutor:
    name = "chat"

    def execute(self, session, run) -> str:
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        message = session.scalar(select(Message).where(Message.run_id == run.id, Message.role == "assistant"))
        if message is None:
            raise ValueError("Chat run has no response message")
        params = run.parameters
        if params.get("provider") != LocalChatProvider.key:
            raise ProviderError("Unsupported chat provider")
        transition(
            session,
            run,
            RunStatus.RUNNING,
            event_type="executor.started",
            payload={"model": params["model"], "location": "local"},
        )
        session.commit()
        try:
            asyncio.run(self._consume(session, run, message))
        except (ProviderError, TimeoutError) as exc:
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            else:
                mark_failed(
                    session, run, "ProviderError", str(exc) or "Local completion exceeded the time limit"
                )
        return "done"

    async def _consume(self, session, run, message):
        params = run.parameters
        stream = LocalChatProvider().stream(
            **{key: params[key] for key in ("endpoint", "messages", "model", "temperature", "max_tokens")}
        )
        pending = None
        try:
            async with asyncio.timeout(600):
                while True:
                    session.refresh(run)
                    canceled = run.status == "cancel_requested"
                    session.commit()
                    if canceled:
                        transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
                        return
                    if pending is None:
                        pending = asyncio.create_task(anext(stream))
                    ready, _ = await asyncio.wait([pending], timeout=0.25)
                    if not ready:
                        continue
                    try:
                        token = pending.result()
                    except StopAsyncIteration:
                        break
                    finally:
                        pending = None
                    if len(message.content) + len(token) > 256000:
                        raise ProviderError("Completion exceeded the output size limit")
                    message.content += token
                    append_event(session, run.id, "chat.delta", {"message_id": message.id, "text": token})
                    session.commit()
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
                return
            if not message.content:
                raise ProviderError("Provider returned no text")
            message.metadata_json = {**message.metadata_json, "partial": False}
            conversation = session.get(Conversation, run.conversation_id)
            conversation.updated_at = utcnow()
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        finally:
            session.commit()
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await pending
            await stream.aclose()
