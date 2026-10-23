"""Reviewed local lyric preparation reuses ordinary agent/music ownership."""

import json
from datetime import timedelta

import pytest
from app.agent_media_schema import AgentMusicScope
from app.api import app
from app.db import session_factory, utcnow
from app.local_provider import LocalChatProvider
from app.models import Agent, Run, Task
from app.music import MusicRequest
from app.resources import active_locks
from app.schedule import scheduler_tick
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create, drain, start
from test_agent_media import implemented_media as implemented_media
from test_music import music_bridge as music_bridge

LYRICS = "[Verse]\nPoranek budzi nowy dzień\n\n[Chorus]\nIdziemy razem tam, gdzie sen"


def scope(**updates):
    return {
        "kind": "music",
        "description_source": "goal",
        "lyrics_source": "goal",
        "request": {
            "caption": "Warm Polish folk",
            "instrumental": False,
            "duration_seconds": 10,
            "lyrics": "A short original Polish chorus about a new start",
            "gpu": "7",
            "seed": 42,
        },
        **updates,
    }


def test_goal_lyrics_allow_pending_words_only_for_reviewed_vocal_goal_mode():
    value = scope()
    value["request"]["lyrics"] = ""
    assert AgentMusicScope.model_validate(value).request.lyrics == ""
    for patch in [{"lyrics_source": "fixed"}, {"description_source": "fixed"}]:
        with pytest.raises(ValueError):
            AgentMusicScope.model_validate({**value, **patch})
    with pytest.raises(ValueError):
        AgentMusicScope.model_validate({**value, "request": {**value["request"], "instrumental": True}})
    # Public/native media cannot use the draft-only empty vocal setting.
    with pytest.raises(ValueError):
        MusicRequest.model_validate(
            {**value["request"], "client_request_id": "d554c61b-5a0c-4186-946d-c070ac387aef"}
        )
    legacy = AgentMusicScope.model_validate({"kind": "music", "request": {"caption": "Piano"}})
    assert legacy.lyrics_source == "fixed" and legacy.request.instrumental


@pytest.mark.parametrize("scheduled", [False, True])
def test_local_lyrics_correction_publication_and_schedule_keep_frozen_settings(
    implemented_media, music_bridge, monkeypatch, scheduled
):
    calls = []

    async def write(self, **kwargs):
        calls.append(kwargs)
        assert kwargs["json_output"] and kwargs["max_tokens"] == 4096
        saved = json.loads(kwargs["messages"][1]["content"])["scope"]
        assert saved["lyrics_source"] == "goal" and "original Polish" in saved["request"]["lyrics"]
        yield json.dumps(
            {
                "description": "Warm acoustic folk",
                "lyrics": LYRICS,
                **({"gpu": "0"} if len(calls) == 1 else {}),
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(LocalChatProvider, "stream", write)
    with TestClient(app) as api:
        agent = create(
            api,
            model="fake-local",
            media=scope(),
            **({"trigger": "interval", "interval_seconds": 60} if scheduled else {}),
        )
        if scheduled:
            with session_factory()() as session:
                row = session.get(Agent, agent["id"])
                row.next_run_at = utcnow() - timedelta(seconds=1)
                session.commit()
                ids = scheduler_tick(session)
                session.commit()
                assert len(ids) == 1
                parent = session.get(Run, ids[0])
                root = {"id": parent.id, "task_id": parent.task_id}
                assert parent.triggered_by == "scheduler"
        else:
            root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            runs = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(row.status == "succeeded" for row in runs), [
                (r.capability, r.error_message) for r in runs
            ]
            child = next(row for row in runs if row.capability == "audio.music")
            assert (
                child.parameters["caption"] == "Warm acoustic folk" and child.parameters["lyrics"] == LYRICS
            )
            assert child.parameters["instrumental"] is False and child.parameters["duration_seconds"] == 10
            assert child.parameters["seed"] == 42 and child.requested_gpu == "7"
            prep = session.get(Run, child.parent_run_id)
            assert child.parameters["execution_deadline_at"] == prep.parameters["execution_deadline_at"]
            assert child.agent_id == agent["id"] and child.task_id == root["task_id"]
            assert prep.parameters["definition"]["media"]["request"]["lyrics"] != LYRICS
            assert not active_locks(session)
        artifact = api.get("/api/artifacts", params={"run_id": child.id}).json()[0]
        assert artifact["metadata"]["lyrics"] == LYRICS and artifact["metadata"]["instrumental"] is False
        assert child.metadata_json["agent_media_preparation_id"] in artifact["parent_artifact_ids"]
        prepared = api.get(f"/api/artifacts/{child.metadata_json['agent_media_preparation_id']}/file").json()
        assert prepared["scope"]["request"]["lyrics"] == LYRICS
        from app.agent_media import publish_media, require_profile

        prepared_scope = AgentMusicScope.model_validate(prepared["scope"])
        profile = require_profile(prepared_scope)
        with session_factory()() as session:
            replay = publish_media(
                session,
                session.get(Run, prep.id),
                prepared_scope,
                profile,
                child.metadata_json["agent_media_preparation_id"],
            )
            assert replay.id == child.id
            assert (
                len(
                    list(
                        session.scalars(
                            select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
                        )
                    )
                )
                == 1
            )
        assert len(calls) == 2
        assert api.get("/api/agents/" + agent["id"]).json()["media"]["request"]["lyrics"] != LYRICS


@pytest.mark.parametrize(
    "output",
    [
        {"description": "Folk"},
        {"description": "Folk", "lyrics": " "},
        {"description": "Folk", "lyrics": "x" * 4097},
        {"description": "Folk", "lyrics": LYRICS, "duration_seconds": 600},
        '{"description":"Folk","lyrics":',
    ],
)
def test_invalid_lyrics_never_dispatch_even_after_bounded_correction(
    implemented_media, music_bridge, monkeypatch, output
):
    calls = []

    async def write(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps(output) if isinstance(output, dict) else output

    monkeypatch.setattr(LocalChatProvider, "stream", write)
    with TestClient(app) as api:
        agent = create(api, model="fake-local", media=scope())
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            prep = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert prep.status == "failed" and "valid bounded" in prep.error_message
            assert (
                session.scalar(
                    select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
                )
                is None
            )
            assert not active_locks(session)
        assert len(calls) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("gpu", "0"),
        ("seed", 17),
        ("duration_seconds", 30),
        ("instrumental", True),
        ("lyrics_source", "fixed"),
    ],
)
def test_publication_cannot_change_reviewed_song_settings(
    implemented_media, music_bridge, monkeypatch, field, value
):
    from app import agent_media

    original = agent_media.publish_media

    async def write(self, **kwargs):
        yield json.dumps({"description": "Folk", "lyrics": LYRICS})

    def change_setting(session, run, prepared, profile, preparation_id):
        prepared = prepared.model_copy(
            update={"lyrics_source": value}
            if field == "lyrics_source"
            else {"request": prepared.request.model_copy(update={field: value})}
        )
        return original(session, run, prepared, profile, preparation_id)

    monkeypatch.setattr(LocalChatProvider, "stream", write)
    monkeypatch.setattr(agent_media, "publish_media", change_setting)
    with TestClient(app) as api:
        agent = create(api, model="fake-local", media=scope())
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            prep = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert prep.status == "failed" and "outside its approved description" in prep.error_message
            assert (
                session.scalar(
                    select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
                )
                is None
            )


def test_stop_during_lyric_preparation_cannot_publish_a_music_child(
    implemented_media, music_bridge, monkeypatch
):
    from app.task_control import cancel_task

    task_id = None

    async def write(self, **kwargs):
        yield '{"description":"Folk",'
        with session_factory()() as session:
            cancel_task(session, session.get(Task, task_id))
            session.commit()
        yield '"lyrics":"Never published"}'

    monkeypatch.setattr(LocalChatProvider, "stream", write)
    with TestClient(app) as api:
        agent = create(api, model="fake-local", media=scope())
        root = start(api, agent)
        task_id = root["task_id"]
        with session_factory()() as session:
            drain(session)
            assert (
                session.scalar(select(Run).where(Run.task_id == task_id, Run.capability == "audio.music"))
                is None
            )
            prep = session.scalar(
                select(Run).where(Run.task_id == task_id, Run.executor_type == "agent_media")
            )
            assert prep.status == "canceled" and not active_locks(session)


@pytest.mark.parametrize("rewrite", [False, True])
def test_supplied_vocals_never_inherit_permission_to_generate_new_words(
    implemented_media, music_bridge, monkeypatch, rewrite
):
    saved = scope(lyrics_source="fixed")
    saved["request"]["lyrics"] = "[Chorus]\nThese exact reviewed words"

    async def write(self, **kwargs):
        assert kwargs["max_tokens"] == 2048
        yield json.dumps({"description": "Quiet folk", **({"lyrics": "Different words"} if rewrite else {})})

    monkeypatch.setattr(LocalChatProvider, "stream", write)
    with TestClient(app) as api:
        agent = create(api, model="fake-local", media=saved)
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            child = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
            )
            if rewrite:
                assert child is None
            else:
                assert (
                    child.status == "succeeded" and child.parameters["lyrics"] == saved["request"]["lyrics"]
                )
