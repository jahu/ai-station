import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory, utcnow
from app.local_provider import LocalChatProvider
from app.models import Artifact, Conversation, Message, Run
from app.paths import safe_join
from app.transcript_context import reference
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_transcription import fake, wav, work


def seed(client, mode="chat"):
    audio = client.post(
        "/api/audio/transcription/uploads", files={"file": ("line.wav", wav(), "audio/wav")}
    ).json()
    cid = client.post("/api/chat/conversations", json={"model": "test", "execution_mode": mode}).json()["id"]
    response = client.post(
        "/api/chat/turns",
        json={
            "client_request_id": str(uuid4()),
            "conversation_id": cid,
            "expected_settings_version": 1,
            "execution_mode": mode,
            "action": "audio.transcribe",
            "content": "Przepisz nagranie",
            "audio_artifact_id": audio["id"],
        },
    )
    assert response.status_code == 202, response.text
    work()
    work()
    with session_factory()() as session:
        child = session.scalar(
            select(Run).where(Run.conversation_id == cid, Run.executor_type == "whisper_transcribe")
        )
        assert child.status == "succeeded"
        message = session.scalar(
            select(Message).where(Message.run_id == child.parent_run_id, Message.role == "assistant")
        )
        return cid, child.id, message.id, child.metadata_json["transcription"]["artifacts"]["txt"]


@pytest.fixture
def providers(monkeypatch):
    fake(monkeypatch)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield "A translated answer from the quoted transcript."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return calls


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_followup_quotes_actual_same_conversation_transcript_and_records_provenance(providers, mode):
    with TestClient(app) as client:
        cid, source_run, source_message, artifact_id = seed(client, mode)
        assert not providers, "Transcription itself must not contact an LLM"
        response = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Przetłumacz to", "action": "chat"}
        )
        assert response.status_code == 202, response.text
        work()
        work()
        assert len(providers) == 1
        prompt = str(providers[0]["messages"])
        assert "Hello" in prompt and "untrusted quoted source data" in prompt and source_run in prompt
        with session_factory()() as session:
            chat = session.scalar(select(Run).where(Run.conversation_id == cid, Run.executor_type == "chat"))
            source = chat.parameters["transcript_sources"][0]
            assert source["run_id"] == source_run and source["artifact_id"] == artifact_id
            assert source["source_message_id"] == source_message and source["available"]
            assert "filesystem_read" not in chat.effective_permissions
            message = session.scalar(
                select(Message).where(Message.run_id == chat.id, Message.role == "assistant")
            )
            assert message.metadata_json["transcript_sources"] == chat.parameters["transcript_sources"]


@pytest.mark.parametrize("problem", ["trashed", "changed", "missing", "other_conversation", "ambiguous"])
def test_reference_never_uses_removed_changed_foreign_or_ambiguous_text(providers, problem):
    with TestClient(app) as client:
        cid, rid, mid, aid = seed(client)
        with session_factory()() as session:
            message, artifact, run = (
                session.get(Message, mid),
                session.get(Artifact, aid),
                session.get(Run, rid),
            )
            path = safe_join(get_settings().data_dir, artifact.relative_path)
            if problem == "trashed":
                artifact.trashed_at = utcnow()
            elif problem == "changed":
                path.write_text("Modified outside the reviewed execution")
            elif problem == "missing":
                path.unlink()
            elif problem == "other_conversation":
                other = Conversation(model="test")
                session.add(other)
                session.flush()
                run.conversation_id = other.id
            else:
                duplicate = Run(
                    id=str(uuid4()),
                    task_id=run.task_id,
                    run_type="audio",
                    capability="audio.transcribe",
                    executor_type="whisper_transcribe",
                    execution_target="host",
                    status="succeeded",
                    conversation_id=cid,
                    parent_run_id=run.parent_run_id,
                )
                session.add(duplicate)
            session.flush()
            result = reference(session, message)
            if problem == "other_conversation":
                assert result is None
            else:
                assert result and not result[1]["available"]
                assert '"text": "Hello"' not in result[0]


def test_context_is_bounded_and_keeps_immutable_artifact_provenance(providers):
    with TestClient(app) as client:
        cid, rid, mid, aid = seed(client)
        with session_factory()() as session:
            run, artifact = session.get(Run, rid), session.get(Artifact, aid)
            segments = [{"start": i / 10, "end": (i + 1) / 10, "text": "x" * 9500} for i in range(8)]
            text = "\n".join(part["text"] for part in segments)
            path = safe_join(get_settings().data_dir, artifact.relative_path)
            path.write_text(text)
            artifact.size_bytes = path.stat().st_size
            artifact.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            run.metadata_json = {
                **run.metadata_json,
                "transcription": {**run.metadata_json["transcription"], "segments": segments, "text": text},
            }
            session.commit()
            quoted = reference(session, session.get(Message, mid), budget=2000)
            assert len(quoted[0]) <= 2000 and quoted[1]["truncated"]
            assert 0 < quoted[1]["included_characters"] < len(text)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Summarize it", "action": "auto", "execution_mode": "chat"},
        )
        assert response.status_code == 202, response.text
        before = response.json()["parameters"]
        with session_factory()() as session:
            source = session.get(Artifact, aid)
            source.trashed_at = utcnow()
            session.commit()
        after = client.get("/api/runs/" + response.json()["id"]).json()["parameters"]
        assert before == after and before["transcript_sources"][0]["available"]
        assert before["transcript_sources"][0]["truncated"]


def test_summary_reads_source_without_changing_original_message_coverage(providers):
    with TestClient(app) as client:
        cid, rid, mid, _ = seed(client)
        with session_factory()() as session:
            messages = list(session.scalars(select(Message).where(Message.conversation_id == cid)))
            original_length = len(session.get(Message, mid).content)
            for i, message in enumerate(sorted(messages, key=lambda value: value.created_at)):
                message.created_at = utcnow() - timedelta(seconds=100 - i)
            for i in range(10):
                session.add(
                    Message(
                        conversation_id=cid,
                        role="user" if i % 2 == 0 else "assistant",
                        content=f"Later message {i}",
                        created_at=utcnow() - timedelta(seconds=90 - i),
                    )
                )
            session.commit()
        response = client.post(f"/api/chat/conversations/{cid}/summarize")
        assert response.status_code == 202, response.text
        params = response.json()["parameters"]
        assert "Hello" in params["messages"][-1]["content"]
        assert params["transcript_sources"][0]["run_id"] == rid
        source_chunk = next(piece for piece in params["source_chunks"] if piece["message_id"] == mid)
        assert source_chunk["total"] == original_length and source_chunk["end"] == original_length
