from uuid import uuid4

import pytest
from app import assistant, music
from app.api import app
from app.assistant import Plan
from app.conversation_music import requested, settings
from app.db import session_factory
from app.engine import tick
from app.models import Run
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from test_music import music_bridge as music_bridge


def conversation(client, mode="chat"):
    response = client.post(
        "/api/chat/conversations", json={"model": "not-running-local", "execution_mode": mode}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_current_music_request_uses_no_text_model_or_default_web_and_returns_audio(
    music_bridge, monkeypatch, mode
):
    def forbidden(*args, **kwargs):
        pytest.fail("A deterministic music request attempted text inference")

    monkeypatch.setattr(assistant, "completion_stream", forbidden)
    original_caps, original_event = music.capabilities, assistant.append_event
    publication = {"started": False, "checks": 0}

    def capabilities():
        assert not publication["started"], "Native I/O happened inside child publication"
        publication["checks"] += 1
        return original_caps()

    def append_event(session, run_id, event_type, payload=None):
        if event_type == "assistant.plan":
            publication["started"] = True
        return original_event(session, run_id, event_type, payload)

    monkeypatch.setattr(music, "capabilities", capabilities)
    monkeypatch.setattr(assistant, "append_event", append_event)
    with TestClient(app) as client:
        cid = conversation(client, mode)
        route = f"/api/chat/conversations/{cid}"
        result = client.post(
            route + "/messages",
            json={
                "content": "Wygeneruj 10 sekund spokojnej muzyki fortepianowej",
                "web_search": {"enabled": True},
                "reasoning": {"enabled": True, "budget": 256},
            },
        )
        assert result.status_code == 202, result.text
        parent_id = result.json()["id"]
        with session_factory()() as session:
            parent = session.get(Run, parent_id)
            assert not parent.parameters["web_search"]["enabled"]
            assert parent.parameters.get("reasoning") is None
            assert "endpoint" not in parent.parameters
            assert tick(session, "music-assistant") == parent_id
            session.refresh(parent)
            child_id = parent.metadata_json["child_run_id"]
            child = session.get(Run, child_id)
            assert child.capability == "audio.music" and child.task_id == parent.task_id
            assert child.parent_run_id == parent.id
            assert child.parameters["duration_seconds"] == 10
            assert set(child.effective_permissions) == {"filesystem_read", "workspace_write"}
            assert tick(session, "music-assistant") == child_id
            assert session.get(Run, child_id).status == "succeeded", session.get(Run, child_id).error_message
        assert publication["checks"] == 1
        message = client.get(route).json()["messages"][-1]
        assert message["task_status"] == "succeeded"
        assert message["artifacts"][0]["type"] == "audio"
        assert message["artifacts"][0]["metadata"]["duration_seconds"] == 10


def test_selected_lyrics_and_length_are_frozen_in_the_same_music_child(music_bridge):
    with TestClient(app) as client:
        cid = conversation(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "action": "audio.music",
                "content": "Warm acoustic folk",
                "music": {
                    "duration_seconds": 10,
                    "instrumental": False,
                    "lyrics": "[Verse]\nQuiet morning",
                    "seed": 42,
                },
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            parent = session.get(Run, response.json()["id"])
            tick(session, "music-lyrics")
            session.refresh(parent)
            child = session.get(Run, parent.metadata_json["child_run_id"])
            assert child.parameters["instrumental"] is False
            assert child.parameters["lyrics"] == "[Verse]\nQuiet morning"
            assert child.parameters["seed"] == 42
            assert child.parameters["duration_seconds"] == 10


def test_missing_runtime_explains_setup_without_publishing_a_music_child(monkeypatch):
    monkeypatch.setattr(music, "capabilities", lambda: {"available": False})
    with TestClient(app) as client:
        cid = conversation(client)
        result = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Generate 30 seconds of ambient music"},
        )
        assert result.status_code == 202, result.text
        with session_factory()() as session:
            tick(session, "music-unavailable")
            assert session.get(Run, result.json()["id"]).status == "succeeded"
        message = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert "needs setup" in message["content"]
        assert message["artifacts"] == []
        assert not client.get("/api/runs", params={"capability": "audio.music"}).json()


def test_a_model_plan_cannot_authorize_music_from_prior_context(monkeypatch):
    async def plan(self, session, run):
        return Plan(action="audio.music", reason="Repeat the previous track")

    monkeypatch.setattr(assistant.AssistantExecutor, "plan", plan)
    monkeypatch.setattr(
        music, "capabilities", lambda: pytest.fail("Unauthorized music queried native runtime")
    )
    with TestClient(app) as client:
        cid = conversation(client, "work")
        result = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "What did you change earlier?"}
        )
        assert result.status_code == 202, result.text
        with session_factory()() as session:
            tick(session, "music-no-plan-permission")
        message = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert "Prior context cannot authorize" in message["content"]
        assert not client.get("/api/runs", params={"capability": "audio.music"}).json()


@pytest.mark.parametrize(
    "extra",
    [
        {"web_search": {"enabled": True, "query": "exact public query"}},
        {"web_search": {"enabled": True, "render_pages": True}},
        {"image_artifact_ids": [str(uuid4())]},
        {"audio_artifact_id": str(uuid4())},
        {"media": {"duration_seconds": 15}},
        {"music": {"duration_seconds": 9}},
        {"music": {"instrumental": False, "lyrics": ""}},
    ],
)
def test_music_rejects_mixed_scope_or_invalid_parameters_before_creating_work(extra):
    with TestClient(app) as client:
        cid = conversation(client)
        result = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Generate ambient music", "action": "audio.music", **extra},
        )
        assert result.status_code == 422, result.text
        assert client.get("/api/runs").json() == []


@pytest.mark.parametrize(
    "text",
    [
        "Wygeneruj 60 sekund spokojnej muzyki",
        "Create a 2 minute piano track",
        "Compose an instrumental soundtrack",
        "Proszę skomponuj podkład jazzowy",
    ],
)
def test_direct_music_intent(text):
    assert requested({"content": text})


@pytest.mark.parametrize(
    "text",
    [
        "Explain how music generation works",
        "Generate a prompt for ambient music",
        "Create a music prompt",
        "Stwórz plan tworzenia muzyki",
        "Create an agent that generates music",
        "Create a project Music",
        "Create a music player app",
        "Create a tracker for bitcoin",
        '"Generate music" is an example',
    ],
)
def test_discussion_examples_and_agent_or_project_goals_do_not_authorize_music(text):
    assert not requested({"content": text})


def test_music_duration_and_vocals_are_not_silently_changed():
    assert settings({"content": "Generate a piano track at 120 BPM for 2 minutes"}).duration_seconds == 120
    assert (
        settings(
            {"content": "Generate music for 2 minutes", "music": {"duration_seconds": 10}}
        ).duration_seconds
        == 10
    )
    with pytest.raises(ValueError, match="duration"):
        settings({"content": "Generate music for 30 minutes"})
    with pytest.raises(ValueError, match="lyrics"):
        settings({"content": "Create a song with vocals"})


def test_repeated_first_send_publishes_only_one_music_child(music_bridge):
    payload = {
        "client_request_id": str(uuid4()),
        "selection": {"execution_mode": "chat", "model": "not-running-local"},
        "content": "Generate 10 seconds of piano music",
        "web_search": {"enabled": True},
    }
    with TestClient(app) as client:
        first = client.post("/api/chat/turns", json=payload)
        assert first.status_code == 202, first.text
        receipt = first.json()
        repeated = client.post("/api/chat/turns", json=payload)
        assert repeated.status_code == 202 and repeated.json() == receipt
        with session_factory()() as session:
            tick(session, "first-music")
        replay = client.post("/api/chat/turns", json=payload)
        assert replay.status_code == 202
        children = client.get("/api/runs", params={"capability": "audio.music"}).json()
        assert len(children) == 1
        assert children[0]["parent_run_id"] == receipt["run"]["id"]


def test_conversation_stop_reaches_the_owned_music_group(music_bridge, monkeypatch):
    original = RunnerClient.request
    task = {}
    with TestClient(app) as client:
        cid = conversation(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "wait",
                "action": "audio.music",
                "music": {"duration_seconds": 10},
            },
        )
        assert response.status_code == 202, response.text
        task["id"] = response.json()["task_id"]

        def request(self, method, path, json=None):
            result = original(self, method, path, json)
            if path == "/v1/runs/music":
                stopped = client.post(f"/api/chat/conversations/{cid}/tasks/{task['id']}/cancel")
                assert stopped.status_code == 200, stopped.text
            return result

        monkeypatch.setattr(RunnerClient, "request", request)
        with session_factory()() as session:
            tick(session, "music-stop")
            child_id = tick(session, "music-stop")
            child = session.get(Run, child_id)
            assert child.capability == "audio.music" and child.status == "canceled"
        assert client.get("/api/artifacts", params={"run_id": child_id}).json() == []


def test_absent_music_scope_preserves_receipts_but_new_music_authority_does_not():
    payload = {
        "client_request_id": str(uuid4()),
        "selection": {"execution_mode": "chat", "model": "not-running-local"},
        "content": "Hello",
    }
    with TestClient(app) as client:
        original = client.post("/api/chat/turns", json=payload)
        assert original.status_code == 202, original.text
        unchanged = client.post("/api/chat/turns", json={**payload, "music": None})
        assert unchanged.status_code == 202 and unchanged.json() == original.json()
        changed = client.post("/api/chat/turns", json={**payload, "music": {}})
        assert changed.status_code == 409
