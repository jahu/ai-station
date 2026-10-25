"""Conversation retries keep results, receipts and failed history on the same Task."""

from uuid import uuid4

import pytest
from app.api import app
from app.assistant import AssistantInputs
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.media_retry_projection import current_attempt, projection
from app.models import Run
from app.runs import create_run, create_task
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_media_jobs import bridge as bridge
from test_media_translation import fake as fake
from test_media_translation import read, settings, work
from test_music import music_bridge as music_bridge
from test_unified_assistant import submit


def image_turn(client, **values):
    return submit(client, "Generate an image of a red bicycle", **values)


def result(client, identifier):
    detail = client.get("/api/chat/conversations/" + identifier)
    assert detail.status_code == 200, detail.text
    return next(item for item in detail.json()["messages"] if item.get("steps"))


def test_absent_media_language_keeps_legacy_request_identity():
    assert "media_translation" not in AssistantInputs().model_dump()
    assert "media_translation" not in AssistantInputs().model_dump(mode="json")
    assert (
        AssistantInputs(media_translation={"mode": "off"}).model_dump()["media_translation"]["mode"] == "off"
    )


@pytest.mark.parametrize(
    "mode,enabled,prepared", [("off", True, False), ("on", False, True), ("inherit", True, True)]
)
def test_unified_turn_forwards_only_media_language_and_freezes_child_policy(
    fake, monkeypatch, mode, enabled, prepared
):
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])
    with TestClient(app) as client:
        policy = settings(client, enabled=enabled)
        turn = image_turn(client, media_translation={"mode": mode, "review": prepared})
        work()
        view = result(client, turn["conversation_id"])
        assert len(view["media_runs"]) == 1
        media = view["media_runs"][0]
        assert media["parameters"]["translation"]["mode"] == mode
        receipt = media["metadata"].get("prompt_translation")
        assert bool(receipt) == prepared
        if prepared:
            prep = read(client, receipt["preparation_run_id"])
            assert prep["parameters"]["policy"]["revision"] == policy["revision"]
            settings(client, enabled=False, model="different-translator")
            work()
            waiting = result(client, turn["conversation_id"])["media_runs"][0]
            assert waiting["metadata"]["prompt_translation"]["status"] == "waiting_for_review"
        else:
            work()
            assert result(client, turn["conversation_id"])["task_status"] == "succeeded"
            assert fake[0] == []


def test_failed_translation_original_recovery_survives_refresh_without_reexecution(fake, monkeypatch):
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])

    async def fail(*_):
        raise ValueError("Translator offline")
        yield

    monkeypatch.setattr("app.media_translation.completion_stream", fail)
    with TestClient(app) as client:
        settings(client)
        turn = image_turn(client)
        for _ in range(3):
            work()
        failed = result(client, turn["conversation_id"])
        assert failed["task_status"] == "failed"
        source = failed["media_runs"][0]
        body = {"translation": "original", "client_request_id": str(uuid4())}
        retried = client.post(f"/api/images/runs/{source['id']}/retry", json=body)
        assert retried.status_code == 202, retried.text
        again = client.post(f"/api/images/runs/{source['id']}/retry", json=body)
        assert again.json()["id"] == retried.json()["id"]
        assert result(client, turn["conversation_id"])["task_status"] == "queued"
        work()
        recovered = result(client, turn["conversation_id"])
        assert recovered["task_status"] == "succeeded"
        assert [item["id"] for item in recovered["media_runs"]] == [retried.json()["id"]]
        assert any(item["id"] == source["id"] and item["superseded"] for item in recovered["steps"])
        assert read(client, source["id"])["status"] == "failed"
        with session_factory()() as db:
            count = len(list(db.scalars(select(Run))))
        assert result(client, turn["conversation_id"]) == recovered
        with session_factory()() as db:
            assert len(list(db.scalars(select(Run)))) == count
        assert len(fake[1]) == 1


@pytest.mark.parametrize("kind", ["music", "video", "film"])
def test_turn_override_reaches_music_and_all_film_segments(request, monkeypatch, kind):
    request.getfixturevalue("music_bridge" if kind == "music" else "bridge")
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])
    action = "audio.music" if kind == "music" else "video.generate"
    with TestClient(app) as client:
        settings(client)
        turn = submit(
            client,
            "calm piano" if kind == "music" else "A calm lake",
            action=action,
            media_translation={"mode": "off"},
            **({"media": {"duration_seconds": 5}} if kind == "film" else {}),
        )
        work()
        with session_factory()() as db:
            children = list(
                db.scalars(
                    select(Run).where(
                        Run.task_id == turn["run"]["task_id"],
                        Run.executor_type.in_(["wan_video", "ace_step_music"]),
                    )
                )
            )
            assert children, [(r.executor_type, r.error_message) for r in db.scalars(select(Run))]
            assert all(child.parameters["translation"]["mode"] == "off" for child in children)
            assert all("prompt_translation" not in child.metadata_json for child in children)
            if kind == "film":
                assert len(children) > 1


def media(session, task, parent=None, **values):
    item = create_run(
        session,
        task,
        run_type="image",
        capability="image.generate",
        executor_type="photo_pipe",
        parent_run_id=parent,
        **values,
    )
    item.status = "failed"
    session.flush()
    return item


@pytest.mark.parametrize(
    "changed",
    ["task_id", "conversation_id", "parent_run_id", "executor_type", "capability", "execution_target"],
)
def test_retry_chain_cannot_cross_request_boundaries(session, changed):
    task = create_task(session, title="Media", prompt="A bicycle", capability="image.generate")
    source = media(session, task)
    retry = media(session, task, source.id)
    source.metadata_json = {"retry_run_id": retry.id}
    setattr(retry, changed, str(uuid4()) if changed.endswith("_id") else "different")
    with session.no_autoflush, pytest.raises(ValueError, match="different request"):
        current_attempt(session, source)


def test_bounded_retry_history_rejects_invalid_references_and_cycles(session):
    task = create_task(session, title="Media", prompt="A bicycle", capability="image.generate")
    source = media(session, task)
    source.metadata_json = {"retry_run_id": "invalid"}
    with pytest.raises(ValueError, match="invalid reference"):
        current_attempt(session, source)
    current = source
    for _ in range(16):
        child = media(session, task, current.id)
        current.metadata_json = {"retry_run_id": child.id}
        current = child
    with pytest.raises(ValueError, match="bound"):
        current_attempt(session, source)
    current.metadata_json = {"retry_run_id": source.id}
    source.parent_run_id = current.id
    with pytest.raises(ValueError):
        current_attempt(session, current)


def test_only_terminal_owned_translation_stages_are_superseded(session):
    task = create_task(session, title="Media", prompt="A bicycle", capability="image.generate")
    source = media(session, task)
    retry = media(session, task, source.id)
    retry.status = "succeeded"
    prep = media(session, task, source.id)
    prep.executor_type = "media_translate"
    load = media(session, task)
    load.executor_type = "llama_load"
    load.metadata_json = {"created_for_consumer": prep.id}
    unrelated = media(session, task)
    unrelated.executor_type = "llama_load"
    source.metadata_json = {"retry_run_id": retry.id, "prompt_translation": {"preparation_run_id": prep.id}}
    session.flush()
    _, retired, errors = projection(session, [source, prep, load, unrelated, retry])
    assert not errors and retired == {source.id, prep.id, load.id}
    load.status = "running"
    prep.status = "running"
    _, retired, _ = projection(session, [source, prep, load, unrelated, retry])
    assert retired == {source.id}
