"""Current-turn original songs share conversation/provider/music contracts."""

import json
from uuid import uuid4

import pytest
from app import conversation_song
from app.api import app
from app.conversation_music import MusicScope
from app.db import session_factory
from app.engine import tick
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_conversation_music import conversation
from test_music import music_bridge as music_bridge

WORDS = "[Chorus]\nSłońce budzi nowy dzień\nIdziemy tam, gdzie nasz sen"


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_natural_song_uses_selected_provider_and_publishes_only_checked_lyrics(
    music_bridge, monkeypatch, mode
):
    calls = []

    async def write(session, params):
        calls.append(params)
        assert (
            params["json_output"] and params["max_tokens"] == 4096 and params["model"] == "not-running-local"
        )
        assert json.loads(params["messages"][1]["content"])["music"]["duration_seconds"] == 10
        yield json.dumps(
            {
                "description": "Warm acoustic folk",
                "lyrics": WORDS,
                **({"gpu": "0"} if len(calls) == 1 else {}),
            }
        )

    monkeypatch.setattr(conversation_song, "completion_stream", write)
    with TestClient(app) as client:
        cid = conversation(client, mode)
        route = f"/api/chat/conversations/{cid}"
        posted = client.post(
            route + "/messages",
            json={"content": "Stwórz 10 sekund piosenki po polsku o słońcu", "web_search": {"enabled": True}},
        )
        assert posted.status_code == 202, posted.text
        rid = posted.json()["id"]
        with session_factory()() as s:
            assert tick(s, "song-writing") == rid
            parent = s.get(Run, rid)
            assert (
                parent.status == "succeeded"
                and parent.parameters["endpoint"]
                and not parent.parameters["web_search"]["enabled"]
            )
            child = s.get(Run, parent.metadata_json["child_run_id"])
            assert child.parameters["lyrics"] == WORDS and child.parameters["caption"] == "Warm acoustic folk"
            assert child.parameters["duration_seconds"] == 10 and not child.parameters["instrumental"]
            assert child.task_id == parent.task_id and child.parent_run_id == parent.id
            preparation_id = child.metadata_json["song_preparation_id"]
            assert child.parameters["parent_artifact_ids"] == [preparation_id]
            assert tick(s, "song-generating") == child.id
            assert s.get(Run, child.id).status == "succeeded"
        assert len(calls) == 2
        message = client.get(route).json()["messages"][-1]
        assert message["task_status"] == "succeeded"
        audio = next(a for a in message["artifacts"] if a["type"] == "audio")
        assert audio["metadata"]["lyrics"] == WORDS and preparation_id in audio["parent_artifact_ids"]
        saved = client.get(f"/api/artifacts/{preparation_id}/file").json()
        assert saved["lyrics"] == WORDS and saved["request"]["lyrics_source"] == "goal"
        events = client.get(f"/api/runs/{rid}/events").json()
        types = [e["event_type"] for e in events]
        assert types.index("assistant.song.prepared") < types.index("assistant.plan")


@pytest.mark.parametrize(
    "output",
    [
        {"description": "Folk"},
        {"description": "Folk", "lyrics": ""},
        {"description": "Folk", "lyrics": "x" * 4097},
        {"description": "Folk", "lyrics": WORDS, "duration_seconds": 600},
        '{"description":"Folk","lyrics":',
    ],
)
def test_invalid_or_truncated_song_output_never_publishes_music(music_bridge, monkeypatch, output):
    calls = []

    async def write(session, params):
        calls.append(params)
        yield json.dumps(output) if isinstance(output, dict) else output

    monkeypatch.setattr(conversation_song, "completion_stream", write)
    with TestClient(app) as client:
        cid = conversation(client)
        posted = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Create a 10 second song with vocals"}
        )
        assert posted.status_code == 202, posted.text
        with session_factory()() as s:
            assert tick(s, "bad-song") == posted.json()["id"]
            run = s.get(Run, posted.json()["id"])
            assert run.status == "failed" and "valid bounded song" in run.error_message
            assert (
                s.scalar(select(Run).where(Run.task_id == run.task_id, Run.capability == "audio.music"))
                is None
            )
        assert len(calls) == 2


def test_selected_song_keeps_duration_seed_gpu_and_replays_the_same_first_send(music_bridge, monkeypatch):
    calls = []

    async def write(session, params):
        calls.append(params)
        yield json.dumps({"description": "Acoustic song", "lyrics": WORDS})

    monkeypatch.setattr(conversation_song, "completion_stream", write)
    payload = {
        "client_request_id": str(uuid4()),
        "selection": {"execution_mode": "chat", "model": "not-running-local"},
        "action": "audio.music",
        "content": "Write an original short Polish chorus about sunrise",
        "music": {
            "lyrics_source": "goal",
            "instrumental": False,
            "lyrics": "Two short lines",
            "duration_seconds": 10,
            "seed": 42,
            "gpu": "7",
        },
    }
    with TestClient(app) as client:
        first = client.post("/api/chat/turns", json=payload)
        assert first.status_code == 202, first.text
        receipt = first.json()
        rid = receipt["run"]["id"]
        assert client.post("/api/chat/turns", json=payload).json() == receipt
        with session_factory()() as s:
            assert tick(s, "first-song") == rid
            parent = s.get(Run, rid)
            child = s.get(Run, parent.metadata_json["child_run_id"])
            assert (
                child.parameters["duration_seconds"] == 10
                and child.parameters["seed"] == 42
                and child.requested_gpu == "7"
            )
            assert set(child.effective_permissions) == {"filesystem_read", "workspace_write"}
        repeated = client.post("/api/chat/turns", json=payload)
        assert repeated.status_code == 202, repeated.text
        assert (
            len(calls) == 1 and len(client.get("/api/runs", params={"capability": "audio.music"}).json()) == 1
        )


def test_stop_during_word_writing_closes_stream_without_publishing_audio(music_bridge, monkeypatch):
    state = {"closed": False}
    with TestClient(app) as client:
        cid = conversation(client)
        route = f"/api/chat/conversations/{cid}"
        posted = client.post(route + "/messages", json={"content": "Create a 10 second song"})
        assert posted.status_code == 202, posted.text

        async def write(session, params):
            try:
                yield '{"description":"Folk",'
                stopped = client.post(route + f"/tasks/{posted.json()['task_id']}/cancel")
                assert stopped.status_code == 200
                yield '"lyrics":"Never published"}'
            finally:
                state["closed"] = True

        monkeypatch.setattr(conversation_song, "completion_stream", write)
        with session_factory()() as s:
            tick(s, "stop-writing")
            run = s.get(Run, posted.json()["id"])
            assert run.status == "canceled"
            assert (
                s.scalar(select(Run).where(Run.task_id == run.task_id, Run.capability == "audio.music"))
                is None
            )
        assert state["closed"]


@pytest.mark.parametrize("permission", ["workspace_write", "external_ai"])
def test_song_writing_checks_effective_permissions_before_inference(music_bridge, monkeypatch, permission):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unauthorized model call")

    monkeypatch.setattr(conversation_song, "completion_stream", forbidden)
    with TestClient(app) as client:
        cid = conversation(client)
        posted = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Create a 10 second song"}
        )
        assert posted.status_code == 202, posted.text
        with session_factory()() as s:
            run = s.get(Run, posted.json()["id"])
            if permission == "external_ai":
                run.parameters = {**run.parameters, "location": "external"}
            run.effective_permissions = [p for p in run.effective_permissions if p != permission]
            s.commit()
            tick(s, "permission-before-song")
            s.refresh(run)
            assert run.status == "failed" and "Unauthorized model call" not in run.error_message
            assert (
                s.scalar(select(Run).where(Run.task_id == run.task_id, Run.capability == "audio.music"))
                is None
            )


def test_fixed_lyrics_source_does_not_change_legacy_scope_serialization():
    expected = {"lyrics": "", "instrumental": True, "duration_seconds": None, "seed": None, "gpu": "auto"}
    assert MusicScope().model_dump(mode="json") == expected
    assert MusicScope(lyrics_source="fixed").model_dump(mode="json") == expected
