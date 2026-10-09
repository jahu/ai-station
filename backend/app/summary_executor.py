"""Cancellable local summary generation; publish only a complete, current result."""

import asyncio
import tempfile
from contextlib import suppress
from pathlib import Path

from app.artifacts import register_file
from app.chat_providers import completion_stream, require_external_permission
from app.conversation_summary import latest_summary, summary_memory
from app.events import append_event
from app.memory import upsert_memory
from app.models import ConversationSummary, Message
from app.providers import ProviderError
from app.runs import mark_failed, transition
from app.serialize import iso
from app.state import RunStatus


class SummaryExecutor:
    name = "chat_summary"

    def execute(self, session, run):
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        if not run.parameters.get("provider"):
            raise ProviderError("Unsupported summary provider")
        require_external_permission(run)
        transition(
            session,
            run,
            RunStatus.RUNNING,
            event_type="executor.started",
            payload={"model": run.parameters["model"], "location": run.parameters.get("location", "local")},
        )
        session.commit()
        try:
            asyncio.run(self.consume(session, run))
        except (ProviderError, TimeoutError) as error:
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            else:
                mark_failed(session, run, "SummaryError", str(error) or "Summary exceeded the time limit")
        return "done"

    async def consume(self, session, run):
        params = run.parameters
        stream = completion_stream(session, params)
        pending, content = None, ""
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
                    if len(content) + len(token) > 8000:
                        raise ProviderError("Summary exceeded 8000 characters; previous summary preserved")
                    content += token
                    append_event(session, run.id, "summary.delta", {"text": token})
                    session.commit()
            session.refresh(run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
                return
            if not content.strip():
                raise ProviderError("Provider returned no summary text")
            prior = latest_summary(session, run.conversation_id)
            memory = summary_memory(session, prior)
            if params["previous_summary_id"] and (
                not prior
                or prior.id != params["previous_summary_id"]
                or not memory
                or memory.id != params["previous_memory_id"]
                or iso(memory.updated_at) != params["previous_memory_updated_at"]
            ):
                raise ProviderError("Previous summary changed during generation; result was not applied")
            source = session.get(Message, params["covered_message_id"])
            if not source or source.conversation_id != run.conversation_id:
                raise ProviderError("Summary source is unavailable")
            covered_offset = params.get("covered_offset") or 0
            if not isinstance(covered_offset, int) or covered_offset < 0:
                raise ProviderError("Summary coverage offset is invalid")
            if covered_offset > len(source.content or ""):
                raise ProviderError("Summary coverage offset exceeds the source message")
            memory = upsert_memory(
                session,
                scope="conversation",
                scope_id=run.conversation_id,
                memory_type="summary",
                content=content,
                tags=["rolling-summary"],
                source_run_id=run.id,
                source_conversation_id=run.conversation_id,
            )
            summary = ConversationSummary(
                conversation_id=run.conversation_id,
                run_id=run.id,
                memory_id=memory.id,
                covered_message_id=source.id,
                covered_created_at=source.created_at,
                covered_offset=covered_offset,
                source_message_ids=params["source_message_ids"],
                previous_summary_id=params["previous_summary_id"],
            )
            session.add(summary)
            session.flush()
            with tempfile.TemporaryDirectory(prefix="ai-station-summary-") as temporary:
                path = Path(temporary) / "summary.md"
                path.write_text(content)
                register_file(
                    session,
                    source=path,
                    artifact_type="markdown",
                    mime_type="text/markdown",
                    original_filename="conversation-summary.md",
                    run_id=run.id,
                    metadata={"summary_id": summary.id, "memory_id": memory.id},
                )
            append_event(
                session,
                run.id,
                "summary.created",
                {
                    "summary_id": summary.id,
                    "memory_id": memory.id,
                    "source_message_ids": params["source_message_ids"],
                    "source_chunks": params.get("source_chunks") or [],
                    "covered_offset": covered_offset,
                },
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        except BaseException:
            session.rollback()
            raise
        finally:
            session.commit()
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await pending
            await stream.aclose()
