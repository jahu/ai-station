import io
import wave
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Run
from app.runner_client import RunnerClient
from app.runs import request_cancel
from fastapi.testclient import TestClient


def wav(seconds=1):
    data = io.BytesIO()
    with wave.open(data, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\0\0" * int(seconds * 8000))
    return data.getvalue()


def fake(monkeypatch, mode="ok"):
    reports = {}

    def request(self, method, path, payload=None):
        if path == "/v1/transcription/capabilities":
            return {
                "available": True,
                "profile_sha256": "a" * 64,
                "formats": ["wav", "mp3", "mov", "ogg", "matroska", "flac"],
            }
        if path == "/v1/runs/transcription":
            rid = payload["run_id"]
            assert set(payload["permissions"]) == {"filesystem_read", "workspace_write"}
            reports[rid] = {
                "run_id": rid,
                "source_sha256": payload["source"]["sha256"],
                "profile_sha256": payload["profile_sha256"],
                "device": "cpu",
                "language": "pl",
                "duration_seconds": 1,
                "text": "Hello",
                "segments": [{"start": 0, "end": 1, "text": "Hello"}],
            }
            if mode == "format_mismatch":
                reports[rid]["input_format"] = "mp3"
            if mode == "mismatch":
                reports[rid]["source_sha256"] = "bad"
            if mode == "cancel":
                with session_factory()() as s:
                    request_cancel(s, s.get(Run, rid))
                    s.commit()
            return {"pid": 12, "process_group_id": 12, "stdout_log": "runs/out", "stderr_log": "runs/err"}
        if path.startswith("/v1/process/") and method == "GET":
            return {
                "alive": False,
                "status": "interrupted" if mode == "uncertain" else "exited",
                "exit_code": None if mode == "uncertain" else 0,
                "stdout": "",
                "stderr": "",
                "stdout_offset": 0,
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
            }
        if path == "/v1/process/cancel":
            return {}
        if path.endswith("/report"):
            return reports[path.split("/")[-2]]
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(RunnerClient, "request", request)


def enqueue(client):
    upload = client.post(
        "/api/audio/transcription/uploads", files={"file": ("speech.wav", wav(), "audio/wav")}
    )
    assert upload.status_code == 201, upload.text
    result = client.post("/api/audio/transcription/runs", json={"audio_artifact_id": upload.json()["id"]})
    assert result.status_code == 202, result.text
    return result.json(), upload.json()


def test_request_receipt_reuses_run_and_rejects_changed_scope(monkeypatch):
    fake(monkeypatch)
    with TestClient(app) as client:
        source = client.post(
            "/api/audio/transcription/uploads", files={"file": ("speech.wav", wav(), "audio/wav")}
        ).json()
        body = {"audio_artifact_id": source["id"], "language": "pl", "client_request_id": str(uuid4())}
        first = client.post("/api/audio/transcription/runs", json=body)
        assert first.status_code == 202, first.text
        work()
        second = client.post("/api/audio/transcription/runs", json=body)
        assert second.status_code == 202
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["status"] == "succeeded"
        changed = client.post("/api/audio/transcription/runs", json={**body, "language": "en"})
        assert changed.status_code == 409
        with session_factory()() as session:
            assert session.get(Run, first.json()["id"]).conversation_id is None


def test_concurrent_request_receipts_enqueue_one_run(monkeypatch):
    from app.models import Task
    from sqlalchemy import func, select

    fake(monkeypatch)
    with TestClient(app) as client:
        source = client.post(
            "/api/audio/transcription/uploads", files={"file": ("speech.wav", wav(), "audio/wav")}
        ).json()
        body = {"audio_artifact_id": source["id"], "client_request_id": str(uuid4())}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda _: client.post("/api/audio/transcription/runs", json=body), range(2))
            )
        assert all(result.status_code == 202 for result in results)
        assert results[0].json()["id"] == results[1].json()["id"]
    with session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Run)) == 1
        assert session.scalar(select(func.count()).select_from(Task)) == 1


def test_receipt_retry_survives_runtime_unavailability(monkeypatch):
    fake(monkeypatch)
    with TestClient(app) as client:
        source = client.post(
            "/api/audio/transcription/uploads", files={"file": ("speech.wav", wav(), "audio/wav")}
        ).json()
        body = {"audio_artifact_id": source["id"], "client_request_id": str(uuid4())}
        first = client.post("/api/audio/transcription/runs", json=body)
        monkeypatch.setattr("app.transcription.capabilities", lambda: {"available": False})
        assert client.post("/api/audio/transcription/runs", json=body).json()["id"] == first.json()["id"]


def work():
    with session_factory()() as s:
        tick(s, "transcription-test")


def test_full_worker_lifecycle_with_timestamped_portable_artifacts(monkeypatch):
    fake(monkeypatch)
    with TestClient(app) as c:
        run, source = enqueue(c)
        work()
        result = c.get("/api/runs/" + run["id"]).json()
        assert result["status"] == "succeeded", result
        transcript = result["metadata"]["transcription"]
        assert transcript["text"] == "Hello"
        assert result["allocated_resources"]["gpu"] == "none"
        artifacts = c.get("/api/artifacts?run_id=" + run["id"]).json()
        assert len(artifacts) == 3
        for a in artifacts:
            assert a["parent_artifact_ids"] == [source["id"]]
            assert not a["relative_path"].startswith("/")
        srt = c.get("/api/artifacts/" + transcript["artifacts"]["srt"] + "/file").text
        assert "00:00:00,000 --> 00:00:01,000" in srt
        assert "Hello" in srt


@pytest.mark.parametrize(
    "mode,status",
    [
        ("cancel", "canceled"),
        ("uncertain", "interrupted"),
        ("mismatch", "failed"),
        ("format_mismatch", "failed"),
    ],
)
def test_failed_canceled_uncertain_never_publish_transcript(monkeypatch, mode, status):
    fake(monkeypatch, mode)
    with TestClient(app) as c:
        run, _ = enqueue(c)
        work()
        assert c.get("/api/runs/" + run["id"]).json()["status"] == status
        assert c.get("/api/artifacts?run_id=" + run["id"]).json() == []


def test_upload_limits_and_separate_voice_contract(monkeypatch):
    fake(monkeypatch)
    with TestClient(app) as c:
        assert (
            c.post(
                "/api/audio/transcription/uploads",
                files={"file": ("bad.wav", b"#EXTM3U\nhttp://localhost/", "audio/wav")},
            ).status_code
            == 422
        )
        assert (
            c.post(
                "/api/audio/transcription/uploads", files={"file": ("long.wav", wav(301), "audio/wav")}
            ).status_code
            == 422
        )
        assert (
            c.post(
                "/api/audio/transcription/uploads", files={"file": ("long.wav", wav(61), "audio/wav")}
            ).status_code
            == 201
        )
        assert (
            c.post("/api/audio/uploads", files={"file": ("long.wav", wav(61), "audio/wav")}).status_code
            == 422
        )


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_conversation_transcription_uses_same_task_and_no_ai_inference(monkeypatch, mode):
    from uuid import uuid4

    from app.local_provider import LocalChatProvider
    from sqlalchemy import select

    async def never(*args, **kwargs):
        raise AssertionError("Transcription must not contact a language model")
        yield

    monkeypatch.setattr(LocalChatProvider, "stream", never)
    fake(monkeypatch)
    with TestClient(app) as client:
        source = client.post(
            "/api/audio/transcription/uploads", files={"file": ("line.wav", wav(), "audio/wav")}
        ).json()
        cid = client.post("/api/chat/conversations", json={"model": "test", "execution_mode": mode}).json()[
            "id"
        ]
        response = client.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "conversation_id": cid,
                "expected_settings_version": 1,
                "content": "Przepisz to nagranie",
                "audio_artifact_id": source["id"],
            },
        )
        assert response.status_code == 202, response.text
        work()
        work()
        with session_factory()() as session:
            runs = list(session.scalars(select(Run).order_by(Run.created_at)))
            assert len(runs) == 2
            assert {run.task_id for run in runs} == {runs[0].task_id}
            assert runs[1].executor_type == "whisper_transcribe"
            assert runs[1].status == "succeeded"
            assert set(runs[1].effective_permissions) == {"filesystem_read", "workspace_write"}


@pytest.mark.parametrize("alive", [True, False, None])
def test_stale_transcription_is_inspected_without_replay(monkeypatch, alive):
    from datetime import timedelta

    from app.db import utcnow
    from app.recovery import recover_stale
    from app.runner_client import RunnerUnavailable
    from sqlalchemy import func, select

    fake(monkeypatch)
    with TestClient(app) as client:
        submitted, _ = enqueue(client)
        with session_factory()() as session:
            run = session.get(Run, submitted["id"])
            run.status = "running"
            run.pid = 42
            run.lease_expires_at = utcnow() - timedelta(seconds=100)
            run.metadata_json = {"dispatch_attempted": True}
            session.commit()

            class Inspector:
                def inspect_process(self, rid):
                    assert rid == run.id
                    if alive is None:
                        raise RunnerUnavailable("offline")
                    return {
                        "alive": alive,
                        "pid": 42,
                        "status": "running" if alive else "exited",
                        "exit_code": None if alive else 0,
                    }

            assert recover_stale(session, Inspector()) == [run.id]
            assert run.status == ("interrupted" if alive is False else "running")
            assert session.scalar(select(func.count()).select_from(Run)) == 1
            session.commit()
        assert client.get("/api/artifacts?run_id=" + submitted["id"]).json() == []


@pytest.mark.parametrize(
    "suffix,mime,content",
    [
        ("mp3", "audio/mpeg", b"ID3" + b"\0" * 20),
        ("m4a", "audio/mp4", b"\0\0\0\x18ftypM4A " + b"\0" * 20),
        ("ogg", "audio/ogg", b"OggS" + b"\0" * 30),
    ],
)
def test_compressed_upload_is_pending_until_worker_validation(monkeypatch, suffix, mime, content):
    fake(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/audio/transcription/uploads", files={"file": ("input." + suffix, content, mime)}
        )
        assert response.status_code == 201, response.text
        artifact = response.json()
        assert artifact["mime_type"] == mime
        assert artifact["relative_path"].endswith("." + suffix)
        assert artifact["metadata"]["duration_validation"] == "pending_transcription"
        assert "duration_seconds" not in artifact["metadata"]
        assert (
            client.post("/api/audio/uploads", files={"file": ("input." + suffix, content, mime)}).status_code
            == 422
        )


def test_older_runner_rejects_new_formats_before_enqueue(monkeypatch):
    def request(self, method, path, payload=None):
        assert path == "/v1/transcription/capabilities"
        return {"available": True, "profile_sha256": "a" * 64}

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        artifact = client.post(
            "/api/audio/transcription/uploads",
            files={"file": ("input.mp3", b"ID3" + b"\0" * 30, "audio/mpeg")},
        ).json()
        response = client.post("/api/audio/transcription/runs", json={"audio_artifact_id": artifact["id"]})
        assert response.status_code == 409, response.text
        assert "Update the Host Runner" in response.json()["detail"]
