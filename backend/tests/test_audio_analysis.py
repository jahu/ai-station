from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Artifact, Message, Run
from app.providers import ProviderError
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_transcription import fake, wav, work


def send(client, *, mode="chat", action="auto", content="Streść to nagranie"):
    source = client.post(
        "/api/audio/transcription/uploads", files={"file": ("recording.wav", wav(), "audio/wav")}
    ).json()
    response = client.post(
        "/api/chat/turns",
        json={
            "client_request_id": str(uuid4()),
            "selection": {"model": "test", "execution_mode": mode},
            "execution_mode": mode,
            "action": action,
            "content": content,
            "audio_artifact_id": source["id"],
        },
    )
    assert response.status_code == 202, response.text
    return response.json(), source


@pytest.fixture
def providers(monkeypatch):
    fake(monkeypatch)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield "A summary of the recording."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return calls


@pytest.mark.parametrize("mode", ["chat", "work"])
@pytest.mark.parametrize("action", ["auto", "audio.analyze"])
def test_one_send_publishes_answer_only_after_successful_transcription(providers, mode, action):
    with TestClient(app) as client:
        receipt, source = send(client, mode=mode, action=action)
        work()
        assert not providers
        with session_factory()() as session:
            runs = list(session.scalars(select(Run).order_by(Run.created_at, Run.id)))
            assert len(runs) == 2 and {run.executor_type for run in runs} == {
                "orchestrator",
                "whisper_transcribe",
            }
        work()
        assert not providers
        with session_factory()() as session:
            transcription = session.scalar(select(Run).where(Run.executor_type == "whisper_transcribe"))
            answer = session.scalar(select(Run).where(Run.executor_type == "chat"))
            assert transcription.status == "succeeded" and answer.status == "queued"
            assert answer.parent_run_id == transcription.id and answer.task_id == receipt["task_id"]
            assert answer.parameters["audio_analysis_source_run_id"] == transcription.id
            assert answer.effective_permissions == [] and set(transcription.effective_permissions) == {
                "filesystem_read",
                "workspace_write",
            }
            assert "Hello" in str(answer.parameters["messages"])
            assert answer.parameters["transcript_sources"][-1]["run_id"] == transcription.id
            assert (
                len(list(session.scalars(select(Artifact).where(Artifact.run_id == transcription.id)))) == 3
            )
        work()
        assert len(providers) == 1 and "Hello" in str(providers[0]["messages"])
        view = client.get("/api/chat/conversations/" + receipt["conversation_id"]).json()
        assert view["active_run"] is None and view["messages"][-1]["content"] == "A summary of the recording."
        assert source["id"] in str(view)


@pytest.mark.parametrize("failure", ["cancel", "uncertain", "mismatch"])
def test_no_answer_is_published_after_unsuccessful_transcription(providers, monkeypatch, failure):
    fake(monkeypatch, mode=failure)
    with TestClient(app) as client:
        send(client)
        work()
        work()
        assert not providers
        with session_factory()() as session:
            assert session.scalar(select(Run).where(Run.executor_type == "chat")) is None


def test_task_stop_prevents_later_answer(providers):
    with TestClient(app) as client:
        receipt, _ = send(client)
        work()
        response = client.post(
            "/api/chat/conversations/"
            + receipt["conversation_id"]
            + "/tasks/"
            + receipt["task_id"]
            + "/cancel"
        )
        assert response.status_code == 200, response.text
        work()
        assert not providers
        with session_factory()() as session:
            assert session.scalar(select(Run).where(Run.executor_type == "chat")) is None


def test_publication_is_idempotent_and_model_failure_preserves_transcript(providers, monkeypatch):
    async def fail(self, **kwargs):
        raise ProviderError("Model is temporarily unavailable")
        yield

    monkeypatch.setattr(LocalChatProvider, "stream", fail)
    with TestClient(app) as client:
        send(client)
        work()
        work()
        from app.audio_analysis import publish_answer

        with session_factory()() as session:
            source = session.scalar(select(Run).where(Run.executor_type == "whisper_transcribe"))
            publish_answer(session, source)
            assert len(list(session.scalars(select(Run).where(Run.executor_type == "chat")))) == 1
            session.commit()
        work()
        with session_factory()() as session:
            assert (
                session.scalar(select(Run).where(Run.executor_type == "whisper_transcribe")).status
                == "succeeded"
            )
            answer = session.scalar(select(Run).where(Run.executor_type == "chat"))
            assert answer.status == "failed"
            assert len(list(session.scalars(select(Artifact)))) == 4
            message = session.scalar(
                select(Message).where(Message.run_id == answer.id, Message.role == "assistant")
            )
            assert "transcript_sources" in message.metadata_json


def test_answer_preparation_failure_keeps_successful_transcript(providers, monkeypatch):
    monkeypatch.setattr("app.audio_analysis.reference", lambda *args, **kwargs: None)
    with TestClient(app) as client:
        send(client)
        work()
        work()
        with session_factory()() as session:
            transcription = session.scalar(select(Run).where(Run.executor_type == "whisper_transcribe"))
            answer = session.scalar(select(Run).where(Run.executor_type == "chat"))
            assert transcription.status == "succeeded"
            assert answer.status == "failed" and answer.error_type == "AudioAnswerPreparationFailed"
            assert len(list(session.scalars(select(Artifact)))) == 4
        assert not providers


def test_provider_endpoint_change_does_not_retarget_answer(providers):
    from app.models import ChatProvider

    with session_factory()() as session:
        session.add(
            ChatProvider(
                key="local-test",
                name="Test endpoint",
                kind="openai-compatible",
                location="local",
                endpoint="http://127.0.0.1:11499/v1",
                enabled=True,
            )
        )
        session.commit()
    with TestClient(app) as client:
        source = client.post(
            "/api/audio/transcription/uploads", files={"file": ("clip.wav", wav(), "audio/wav")}
        ).json()
        response = client.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "selection": {"provider": "local-test", "model": "test", "execution_mode": "chat"},
                "execution_mode": "chat",
                "content": "Summarize this recording",
                "audio_artifact_id": source["id"],
            },
        )
        assert response.status_code == 202, response.text
        work()
        with session_factory()() as session:
            provider = session.scalar(select(ChatProvider).where(ChatProvider.key == "local-test"))
            provider.endpoint = "http://127.0.0.1:11500/v1"
            session.commit()
        work()
        with session_factory()() as session:
            answer = session.scalar(select(Run).where(Run.executor_type == "chat"))
            assert answer.parameters["endpoint"] == "http://127.0.0.1:11499/v1"
        work()
        with session_factory()() as session:
            assert session.scalar(select(Run).where(Run.executor_type == "chat")).status == "failed"
            assert (
                session.scalar(select(Run).where(Run.executor_type == "whisper_transcribe")).status
                == "succeeded"
            )
        assert not providers


def test_silence_does_not_load_or_call_response_model(providers, monkeypatch):
    from app.runner_client import RunnerClient

    previous = RunnerClient.request

    def request(self, method, path, payload=None):
        result = previous(self, method, path, payload)
        if path.endswith("/report"):
            result = {**result, "text": "", "segments": []}
        return result

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        receipt, _ = send(client)
        work()
        work()
        assert not providers
        view = client.get("/api/chat/conversations/" + receipt["conversation_id"]).json()
        assert "No speech was detected" in view["messages"][-1]["content"]
        with session_factory()() as session:
            assert session.scalar(select(Run).where(Run.executor_type == "chat")) is None
            assert (
                session.scalar(select(Run).where(Run.executor_type == "whisper_transcribe")).status
                == "succeeded"
            )


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_recording_upload_preserves_supported_pcm_widths(providers, width):
    import io
    import wave

    from ai_station_runner.transcription_protocol import wav_info

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(width)
        handle.setframerate(16000)
        handle.writeframes(b"\0" * 16000 * width)
    content = buffer.getvalue()
    assert wav_info(content)["duration_seconds"] == 1
    with TestClient(app) as client:
        response = client.post(
            "/api/audio/transcription/uploads", files={"file": ("clip.wav", content, "audio/wav")}
        )
        assert response.status_code == 201, response.text


def test_generic_recording_question_routes_without_classifier_call(providers):
    with TestClient(app) as client:
        send(client, content="Jak brzmią pierwsze trzy słowa nagrania?")
        work()
        work()
        work()
        assert len(providers) == 1
        assert "Hello" in str(providers[0]["messages"])


def test_model_settings_change_preserves_transcript_and_fails_answer(providers):
    from app.models import Conversation

    with TestClient(app) as client:
        receipt, _ = send(client)
        work()
        with session_factory()() as session:
            session.get(Conversation, receipt["conversation_id"]).model = "different-model"
            session.commit()
        work()
        with session_factory()() as session:
            answer = session.scalar(select(Run).where(Run.executor_type == "chat"))
            assert answer.status == "failed" and "settings changed" in answer.error_message
            assert (
                session.scalar(select(Run).where(Run.executor_type == "whisper_transcribe")).status
                == "succeeded"
            )
        assert not providers


def test_stop_after_transcription_cancels_queued_answer(providers):
    with TestClient(app) as client:
        receipt, _ = send(client)
        work()
        work()
        response = client.post(
            "/api/chat/conversations/"
            + receipt["conversation_id"]
            + "/tasks/"
            + receipt["task_id"]
            + "/cancel"
        )
        assert response.status_code == 200, response.text
        work()
        with session_factory()() as session:
            assert session.scalar(select(Run).where(Run.executor_type == "chat")).status == "canceled"
            assert (
                session.scalar(select(Run).where(Run.executor_type == "whisper_transcribe")).status
                == "succeeded"
            )
        assert not providers
