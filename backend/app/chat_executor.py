"""Cancellable local completion using the shared Run lifecycle and persisted deltas."""

import asyncio
from contextlib import suppress

from sqlalchemy import select

from app.chat_providers import completion_stream, require_external_permission
from app.db import utcnow
from app.events import append_event
from app.models import Conversation, Message
from app.providers import ProviderError
from app.runs import mark_failed, transition
from app.state import RunStatus

DELIVERY_INTERVAL = 0.1
CANCELLATION_INTERVAL = 0.25
DELIVERY_CHARACTERS = 4096


class _DeliveryBuffer:
    """Bound live output without reserving a SQLite writer while awaiting tokens."""

    def __init__(self, session, run, message, clock):
        self.session, self.run, self.message, self.clock = session, run, message, clock
        self.kind = None
        self.parts = []
        self.characters = 0
        self.delivered = set()
        self.deadline = clock() + DELIVERY_INTERVAL

    def add(self, value):
        from app.chat_reasoning import ReasoningDelta

        kind, text = ("reasoning", value.text) if isinstance(value, ReasoningDelta) else ("text", value)
        if self.kind is not None and self.kind != kind:
            self.flush()
        saved = (
            self.message.metadata_json.get("reasoning_text", "")
            if kind == "reasoning"
            else self.message.content
        )
        limit = 65536 if kind == "reasoning" else 256000
        if len(saved) + self.characters + len(text) > limit:
            raise ProviderError(
                "Thinking output exceeded its bound"
                if kind == "reasoning"
                else "Completion exceeded the output size limit"
            )
        if not self.parts:
            self.deadline = self.clock() + DELIVERY_INTERVAL
        self.kind = kind
        self.parts.append(text)
        self.characters += len(text)

    def flush(self):
        if not self.parts:
            return
        text, kind = "".join(self.parts), self.kind
        self.parts, self.kind, self.characters = [], None, 0
        try:
            if kind == "reasoning":
                self.message.metadata_json = {
                    **self.message.metadata_json,
                    "reasoning_text": self.message.metadata_json.get("reasoning_text", "") + text,
                }
                event_type = "chat.reasoning_delta"
            else:
                self.message.content += text
                event_type = "chat.delta"
            append_event(self.session, self.run.id, event_type, {"message_id": self.message.id, "text": text})
            self.session.commit()
            self.delivered.add(kind)
        except BaseException:
            self.session.rollback()
            raise


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
        if not params.get("provider"):
            raise ProviderError("Unsupported chat provider")
        require_external_permission(run)
        transition(
            session,
            run,
            RunStatus.RUNNING,
            event_type="executor.started",
            payload={"model": params["model"], "location": params.get("location", "local")},
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
        from app.web_search import context

        if run.parameters.get("page_read"):
            from app.chat_pages import page_context

            messages = await page_context(session, run, message)
        else:
            messages = await context(session, run, message)
        if messages is None:
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            session.commit()
            return
        if (
            run.parameters.get("image_followup")
            and not message.metadata_json.get("page_read")
            and not message.metadata_json.get("web_search", {}).get("sources")
        ):
            raise ProviderError("No usable search sources were returned for this image")
        if run.parameters.get("vision_artifact_ids"):
            from app.vision import image_context

            messages = image_context(session, run, messages)
        params = {**run.parameters, "messages": messages}
        stream = completion_stream(session, params)
        # Binding the provider can read private/model records. Finish that
        # transaction before waiting on any network output.
        session.commit()
        loop = asyncio.get_running_loop()
        delivery = _DeliveryBuffer(session, run, message, loop.time)
        next_check = loop.time()
        pending = None
        try:
            async with asyncio.timeout(600):
                while True:
                    if loop.time() >= next_check:
                        session.refresh(run)
                        canceled = run.status == "cancel_requested"
                        session.commit()
                        next_check = loop.time() + CANCELLATION_INTERVAL
                        if canceled:
                            delivery.flush()
                            transition(
                                session, run, RunStatus.CANCELED, event_type="run.canceled", payload={}
                            )
                            return
                    if pending is None:
                        pending = asyncio.create_task(anext(stream))
                    deadline = min(next_check, delivery.deadline) if delivery.parts else next_check
                    ready, _ = await asyncio.wait([pending], timeout=max(0, deadline - loop.time()))
                    if not ready:
                        if delivery.parts and loop.time() >= delivery.deadline:
                            delivery.flush()
                        continue
                    try:
                        token = pending.result()
                    except StopAsyncIteration:
                        break
                    finally:
                        pending = None
                    from app.chat_reasoning import CompletionFinished

                    if isinstance(token, CompletionFinished):
                        delivery.flush()
                        message.metadata_json = {**message.metadata_json, "finish_reason": token.reason}
                        session.commit()
                        if token.reason == "length":
                            raise ProviderError(
                                "Output budget exhausted; the partial answer and thinking are preserved"
                            )
                        continue

                    delivery.add(token)
                    if (
                        delivery.kind not in delivery.delivered
                        or delivery.characters >= DELIVERY_CHARACTERS
                        or loop.time() >= delivery.deadline
                    ):
                        delivery.flush()
            delivery.flush()
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
                return
            if not message.content:
                raise ProviderError("Provider returned no text")
            if run.parameters.get("vision_artifact_ids"):
                from app.vision import save_description

                save_description(session, run, message)
            message.metadata_json = {**message.metadata_json, "partial": False}
            if run.parameters.get("image_followup"):
                from app.image_research import publish_image

                publish_image(session, run, message)
            conversation = session.get(Conversation, run.conversation_id)
            conversation.updated_at = utcnow()
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
            from app.conversation_summary import maybe_enqueue_automatic_summary

            if not run.parameters.get("image_followup"):
                maybe_enqueue_automatic_summary(session, conversation, run)
        finally:
            # A failed flush invalidates the transaction. Preserve the original
            # error and always close inference, even if persistence fails.
            try:
                if session.is_active:
                    delivery.flush()
                    session.commit()
                else:
                    session.rollback()
            finally:
                if pending is not None:
                    pending.cancel()
                    with suppress(asyncio.CancelledError, StopAsyncIteration):
                        await pending
                await stream.aclose()
