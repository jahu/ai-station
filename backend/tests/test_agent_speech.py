import json
import time
from uuid import uuid4

import pytest
from ai_station_runner import app as native
from app import agent_media
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Notice, Run
from app.resources import active_locks
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create, drain, no_text_model, start
from test_audio import audio_bridge as audio_bridge
from test_audio import reference


@pytest.fixture
def speech_enabled(monkeypatch):
    monkeypatch.setattr(agent_media, "SPEECH_AGENTS_ENABLED", True)


def test_fixed_speech_reuses_reviewed_voice_without_a_text_model(speech_enabled, audio_bridge, monkeypatch):
    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        voice = reference(api)
        agent = create(
            api,
            kind="speech",
            request={"text": "Witaj w AI Station", "reference_artifact_id": voice["id"]},
            notification_policy={"on_success": True, "on_failure": True},
        )
        root = start(api, agent)
        with session_factory()() as s:
            tick(s, "speech-root")
            tick(s, "speech-prepare")
            assert not list(s.scalars(select(Notice)))
            drain(s)
            runs = list(s.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert len(runs) == 3 and all(r.status == "succeeded" for r in runs), [
                (r.status, r.error_message) for r in runs
            ]
            speech = next(r for r in runs if r.executor_type == "chatterbox")
            prep = s.get(Run, speech.parent_run_id)
            assert speech.parameters["execution_deadline_at"] == prep.parameters["execution_deadline_at"]
            assert speech.agent_id == agent["id"] and not active_locks(s)
            notices = list(s.scalars(select(Notice)))
            assert len(notices) == 1 and notices[0].run_id == speech.id
            assert notices[0].title == "Agent media ready"
            process = native.manager().inspect(speech.id)
            assert process["deadline_at"] > 0 and not process["alive"]
        artifact = api.get("/api/artifacts", params={"run_id": speech.id}).json()[0]
        assert artifact["mime_type"] == "audio/wav" and voice["id"] in artifact["parent_artifact_ids"]
        assert prep.metadata_json["media_run_id"] == speech.id


def test_goal_speech_only_rewrites_bounded_spoken_text(speech_enabled, audio_bridge, monkeypatch):
    calls = []

    async def stream(self, **params):
        calls.append(params)
        yield json.dumps({"description": "a" * 1001 if len(calls) == 1 else "Krótki polski komunikat."})

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as api:
        voice = reference(api)
        agent = create(
            api,
            model="fake-local",
            media={
                "kind": "speech",
                "description_source": "goal",
                "request": {"text": "Say hello in Polish", "reference_artifact_id": voice["id"], "gpu": "7"},
            },
        )
        root = start(api, agent)
        with session_factory()() as s:
            drain(s)
            speech = s.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "chatterbox")
            )
            assert speech and speech.status == "succeeded", [
                (r.status, r.error_message) for r in s.scalars(select(Run))
            ]
            assert speech.parameters["text"] == "Krótki polski komunikat."
            assert speech.parameters["parent_artifact_ids"][0] == voice["id"] and speech.requested_gpu == "7"
        assert len(calls) == 2 and "exact Polish text" in calls[0]["messages"][0]["content"]


def test_native_speech_budget_expires_without_a_worker(audio_bridge):
    with TestClient(app) as api:
        voice = reference(api)
        rid = str(uuid4())
        response = audio_bridge.post(
            "/v1/runs/audio",
            json={
                "run_id": rid,
                "text": "wait",
                "reference_relative": voice["relative_path"],
                "gpu": 7,
                "permissions": ["filesystem_read", "workspace_write"],
                "deadline_at": time.time() + 0.5,
            },
        )
        assert response.status_code == 200, response.text
        until = time.monotonic() + 5
        while time.monotonic() < until:
            process = native.manager().inspect(rid)
            if not process["alive"] and not process["completion_pending"]:
                break
            time.sleep(0.03)
        assert process["status"] == "canceled" and process["deadline_exceeded_at"]
        assert api.get("/api/artifacts", params={"run_id": rid}).json() == []


def test_changed_voice_bytes_stop_before_publication(speech_enabled, audio_bridge):
    from app.config import get_settings

    with TestClient(app) as api:
        voice = reference(api)
        agent = create(api, kind="speech", request={"text": "Witaj", "reference_artifact_id": voice["id"]})
        root = start(api, agent)
        path = get_settings().data_dir / voice["relative_path"]
        content = bytearray(path.read_bytes())
        content[-1] ^= 1
        path.write_bytes(content)
        with session_factory()() as s:
            drain(s)
            runs = list(s.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert not any(r.executor_type == "chatterbox" for r in runs)
            failed = next(r for r in runs if r.executor_type == "agent_media")
            assert failed.status == "failed" and "checksum" in failed.error_message


def test_stop_before_speech_preparation_never_dispatches(speech_enabled, audio_bridge):
    with TestClient(app) as api:
        voice = reference(api)
        agent = create(api, kind="speech", request={"text": "Witaj", "reference_artifact_id": voice["id"]})
        root = start(api, agent)
        with session_factory()() as s:
            tick(s, "speech-root")
        assert api.post("/api/runs/" + root["id"] + "/cancel").status_code == 200
        with session_factory()() as s:
            drain(s)
            runs = list(s.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert not any(r.executor_type == "chatterbox" for r in runs)
            assert any(r.executor_type == "agent_media" and r.status == "canceled" for r in runs)


def test_expired_native_speech_budget_cannot_launch(audio_bridge):
    from ai_station_runner.processes import ProcessNotOwned

    with TestClient(app) as api:
        voice = reference(api)
        rid = str(uuid4())
        response = audio_bridge.post(
            "/v1/runs/audio",
            json={
                "run_id": rid,
                "text": "Hello",
                "reference_relative": voice["relative_path"],
                "gpu": 7,
                "permissions": ["filesystem_read", "workspace_write"],
                "deadline_at": time.time() - 1,
            },
        )
        assert response.status_code == 422, response.text
        with pytest.raises(ProcessNotOwned):
            native.manager().inspect(rid)


def test_task_stop_reaches_a_launched_speech_process(speech_enabled, audio_bridge, monkeypatch):
    from app.runner_client import RunnerClient

    original = RunnerClient.request
    with TestClient(app) as api:
        voice = reference(api)
        agent = create(api, kind="speech", request={"text": "wait", "reference_artifact_id": voice["id"]})
        root = start(api, agent)

        def request(self, method, path, json=None):
            result = original(self, method, path, json)
            if path == "/v1/runs/audio":
                assert api.post("/api/runs/" + root["id"] + "/cancel").status_code == 200
            return result

        monkeypatch.setattr(RunnerClient, "request", request)
        with session_factory()() as s:
            drain(s)
            speech = s.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "chatterbox")
            )
            assert speech.status == "canceled" and not active_locks(s)
            assert not native.manager().inspect(speech.id)["alive"]
        assert api.get("/api/artifacts", params={"run_id": speech.id}).json() == []


def test_speech_publication_is_idempotent_without_runner_io(speech_enabled, audio_bridge, monkeypatch):
    from app.agent_schema import AgentSettings
    from app.runner_client import RunnerClient

    original_publish, original_request = agent_media.publish_media, RunnerClient.request
    inside = {"publication": False}

    def publish(*args, **kwargs):
        inside["publication"] = True
        try:
            return original_publish(*args, **kwargs)
        finally:
            inside["publication"] = False

    def request(self, method, path, json=None):
        assert not inside["publication"], "Runner HTTP inside speech publication"
        return original_request(self, method, path, json)

    monkeypatch.setattr(agent_media, "publish_media", publish)
    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as api:
        voice = reference(api)
        agent = create(api, kind="speech", request={"text": "Hello", "reference_artifact_id": voice["id"]})
        root = start(api, agent)
        with session_factory()() as s:
            tick(s, "speech-root")
            stage = s.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            tick(s, "speech-prepare")
            s.refresh(stage)
            child = s.get(Run, stage.metadata_json["media_run_id"])
            scope = AgentSettings.model_validate(stage.parameters["definition"]).media
            replay = publish(
                s,
                stage,
                scope,
                agent_media.require_profile(scope),
                child.metadata_json["agent_media_preparation_id"],
            )
            assert replay.id == child.id
            assert (
                len(
                    list(
                        s.scalars(
                            select(Run).where(
                                Run.task_id == root["task_id"], Run.executor_type == "chatterbox"
                            )
                        )
                    )
                )
                == 1
            )


def test_expired_speech_worker_lease_cleans_up_without_replaying(speech_enabled, audio_bridge):
    from datetime import timedelta

    from app.db import utcnow
    from app.recovery import recover_stale
    from app.resources import reserve_gpu
    from app.runs import claim_next, transition

    with TestClient(app) as api:
        voice = reference(api)
        agent = create(api, kind="speech", request={"text": "wait", "reference_artifact_id": voice["id"]})
        root = start(api, agent)
        with session_factory()() as s:
            tick(s, "speech-root")
            tick(s, "speech-prepare")
            run = claim_next(s, "lost-speech-worker")
            assert run.executor_type == "chatterbox" and run.task_id == root["task_id"]
            transition(s, run, "preparing", event_type="executor.preparing")
            assert reserve_gpu(s, run, [7]) == "7"
            s.commit()
            response = audio_bridge.post(
                "/v1/runs/audio",
                json={
                    "run_id": run.id,
                    "text": "wait",
                    "reference_relative": voice["relative_path"],
                    "gpu": 7,
                    "permissions": ["filesystem_read", "workspace_write"],
                    "deadline_at": time.time() + 30,
                },
            )
            assert response.status_code == 200, response.text
            process = response.json()
            transition(s, run, "running", event_type="executor.started")
            run.pid = process["pid"]
            run.parameters = {
                **run.parameters,
                "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
            }
            for _ in range(2):
                run.lease_expires_at = utcnow() - timedelta(seconds=1)
                s.commit()
                recover_stale(s)
                s.commit()
            s.refresh(run)
            assert run.status == "canceled" and not active_locks(s)
            final = native.manager().inspect(run.id)
            assert not final["alive"] and final["pid"] == process["pid"]
        assert api.get("/api/artifacts", params={"run_id": run.id}).json() == []


@pytest.mark.parametrize("damage", ["missing", "invalid"])
def test_invalid_voice_cannot_activate_or_enqueue_work(speech_enabled, audio_bridge, damage):
    from app.config import get_settings

    with TestClient(app) as api:
        voice = reference(api)
        path = get_settings().data_dir / voice["relative_path"]
        if damage == "missing":
            path.unlink()
        else:
            path.write_bytes(b"not a wave recording")
        response = api.post(
            "/api/agents",
            json={
                "name": "Voice validation",
                "goal": "Read a welcome",
                "enabled": True,
                "tools": ["create_media"],
                "media": {
                    "kind": "speech",
                    "request": {"text": "Hello", "reference_artifact_id": voice["id"]},
                },
            },
        )
        assert response.status_code == 409 and "intact WAV" in response.text
        assert api.get("/api/runs").json() == []
