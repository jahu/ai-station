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
                    from app.chat_reasoning import CompletionFinished, ReasoningDelta

                    if isinstance(token, CompletionFinished):
                        message.metadata_json = {**message.metadata_json, "finish_reason": token.reason}
                        if token.reason == "length":
                            raise ProviderError(
                                "Output budget exhausted; the partial answer and thinking are preserved"
                            )
                        continue

                    if isinstance(token, ReasoningDelta):
                        text = message.metadata_json.get("reasoning_text", "") + token.text
                        if len(text) > 65536:
                            raise ProviderError("Thinking output exceeded its bound")
                        message.metadata_json = {**message.metadata_json, "reasoning_text": text}
                        append_event(
                            session,
                            run.id,
                            "chat.reasoning_delta",
                            {"message_id": message.id, "text": token.text},
                        )
                        session.commit()
                        continue
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
            session.commit()
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await pending
            await stream.aclose()
