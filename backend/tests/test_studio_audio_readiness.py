"""Cold native metadata checks wait; ordinary unavailability still fails."""

from datetime import timedelta
from uuid import uuid4

import pytest
from app import fish_speech, music
from app import studio_audio_production as production
from app.audio_schema import SpeechRequest
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run, RunEvent
from app.runtime_readiness import CapabilityChecking, reject_checking
from app.state import TERMINAL
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_studio_audio_production import app, generators, submit, two_shots  # noqa: F401


@pytest.mark.parametrize("stage", ["speech", "music"])
def test_checking_waits_without_replaying_completed_cues_or_score(generators, monkeypatch, stage):  # noqa: F811
    speech, scores, executors = generators
    publisher = "create_audio_run" if stage == "speech" else "create_music_run"
    original = getattr(production, publisher)
    checking = True

    def publish(*args, **kwargs):
        if checking:
            raise CapabilityChecking("audio." + stage, "Verifying model files")
        return original(*args, **kwargs)

    monkeypatch.setattr(production, publisher, publish)
    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as db:
            waiting_id = None
            for _ in range(12):
                tick(db, "cold-audio", executors=executors)
                waiting = db.scalar(select(Run).where(Run.task_id == root["task_id"], Run.status == "queued"))
                if waiting and waiting.metadata_json.get("studio_audio_verification"):
                    waiting_id = waiting.id
                    break
            assert waiting_id
            assert len(speech) == (0 if stage == "speech" else 2)
            assert not scores
            for _ in range(3):
                assert tick(db, "backed-off-audio", executors=executors) is None
            # Ordinary stale-process recovery must not classify this queue-only
            # wait as a lost native process or manufacture another coordinator.
            assert db.get(Run, waiting_id).status == "queued"
            checking = False
            waiting = db.get(Run, waiting_id)
            waiting.metadata_json = {
                **waiting.metadata_json,
                "resource_wait_until": (utcnow() - timedelta(seconds=1)).isoformat(),
            }
            db.commit()
            for _ in range(20):
                tick(db, "warm-audio", executors=executors)
                rows = list(db.scalars(select(Run).where(Run.task_id == root["task_id"])))
                if all(r.status in TERMINAL for r in rows):
                    break
            assert all(r.status == "succeeded" for r in rows), [
                (r.executor_type, r.status, r.error_message) for r in rows
            ]
            assert db.get(Run, waiting_id).status == "succeeded"
            assert len(speech) == 2 and len(scores) == 1
            events = list(db.scalars(select(RunEvent).where(RunEvent.run_id == waiting_id)))
            assert any(e.event_type == "studio.audio.verifying" for e in events)


@pytest.mark.parametrize("action", ["stop", "timeout", "unavailable"])
def test_checking_is_bounded_and_stoppable(generators, monkeypatch, action):  # noqa: F811
    def publish(*args, **kwargs):
        raise CapabilityChecking("audio.speech", "Verifying model files")

    monkeypatch.setattr(production, "create_audio_run", publish)
    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as db:
            tick(db, "cold-audio", executors=generators[2])
            run = db.get(Run, root["id"])
            assert run.status == "queued"
            if action == "timeout":
                run.metadata_json = {
                    **run.metadata_json,
                    "studio_audio_verification": {
                        "capability": "audio.speech",
                        "started_at": (utcnow() - timedelta(minutes=6)).isoformat(),
                    },
                }
            run.metadata_json = {
                **run.metadata_json,
                "resource_wait_until": (utcnow() - timedelta(seconds=1)).isoformat(),
            }
            db.commit()
        if action == "stop":
            assert (
                client.post(f"/api/studio/materials/{row['id']}/audio/{root['id']}/stop").status_code == 200
            )
        elif action == "unavailable":

            def unavailable(*args, **kwargs):
                raise HTTPException(409, "Model files are unavailable")

            monkeypatch.setattr(production, "create_audio_run", unavailable)
        with session_factory()() as db:
            tick(db, "waiting-audio", executors=generators[2])
            run = db.get(Run, root["id"])
            assert run.status == ("canceled" if action == "stop" else "failed")
            if action == "timeout":
                assert "verification did not finish" in run.error_message
            if action == "unavailable":
                assert "Model files are unavailable" in run.error_message
            assert len(list(db.scalars(select(Run).where(Run.task_id == root["task_id"])))) == 1
            assert not generators[0] and not generators[1]


@pytest.mark.parametrize("engine", ["speech", "music"])
def test_real_publisher_reports_typed_checking_with_original_http_contract(monkeypatch, engine):
    report = {"available": False, "readiness": "checking", "reason": "Verifying installed files"}
    if engine == "speech":
        monkeypatch.setattr(fish_speech, "capabilities", lambda: {"engines": {"fish_s2_pro": report}})

        def call(db):
            return fish_speech.create_fish_run(
                db,
                SpeechRequest(
                    text="A real request",
                    reference_artifact_id=None,
                    engine="fish_s2_pro",
                    voice_source="model",
                ),
                None,
            )
    else:
        monkeypatch.setattr(music, "capabilities", lambda: report)

        def call(db):
            return music.create_music_run(
                db,
                music.MusicRequest(
                    client_request_id=uuid4(), caption="Calm instrumental", duration_seconds=15
                ),
            )

    with session_factory()() as db:
        with pytest.raises(CapabilityChecking) as caught:
            call(db)
        assert caught.value.status_code == 409 and caught.value.detail == report["reason"]
        assert not list(db.scalars(select(Run)))


@pytest.mark.parametrize(
    "report",
    [
        {"available": False},
        {"available": False, "readiness": "unavailable"},
        {"available": True, "readiness": "checking"},
    ],
)
def test_only_explicit_pending_verification_is_transient(report):
    reject_checking(report, "audio.speech")


@pytest.mark.parametrize("winner", ["stop", "new_claim"])
def test_pending_reply_cannot_overwrite_stop_or_new_worker_claim(generators, monkeypatch, winner):  # noqa: F811
    pending_seen = False

    def pending(*args, **kwargs):
        nonlocal pending_seen
        pending_seen = True
        raise CapabilityChecking("audio.speech", "Verifying model files")

    monkeypatch.setattr(production, "create_audio_run", pending)
    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as db:
            original_rollback = db.rollback

            def rollback():
                nonlocal pending_seen
                original_rollback()
                if not pending_seen:
                    return
                pending_seen = False
                from app.task_control import cancel_task

                with session_factory()() as concurrent:
                    current = concurrent.get(Run, root["id"])
                    if winner == "stop":
                        cancel_task(concurrent, current.task)
                    else:
                        current.worker_id = "new-worker"
                        current.claimed_at = utcnow() + timedelta(seconds=1)
                    concurrent.commit()

            monkeypatch.setattr(db, "rollback", rollback)
            tick(db, "old-worker", executors=generators[2])
            current = db.get(Run, root["id"])
            assert current.status == ("canceled" if winner == "stop" else "running")
            assert "studio_audio_verification" not in current.metadata_json
            if winner == "new_claim":
                assert current.worker_id == "new-worker"
            assert not generators[0] and not generators[1]


@pytest.mark.parametrize("kind", ["audio", "music"])
def test_selected_installed_model_preserves_pending_native_state(monkeypatch, kind):
    from app import audio_models, music_models

    module = audio_models if kind == "audio" else music_models
    model = {
        "checkpoint": {"sha256": "a" * 64},
        "binding": {"managed_runtime": {"manifest_sha256": "b" * 64}},
    }
    monkeypatch.setattr(module, "frozen_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(
        module.RunnerClient, "request", lambda *args: {"available": False, "readiness": "checking"}
    )
    with session_factory()() as db:
        with pytest.raises(CapabilityChecking) as caught:
            module.profile_for(db, uuid4())
        assert caught.value.capability == ("audio.speech" if kind == "audio" else "audio.music")


def test_direct_http_speech_request_keeps_409_during_verification(monkeypatch):
    monkeypatch.setattr(
        fish_speech,
        "capabilities",
        lambda: {
            "engines": {
                "fish_s2_pro": {"available": False, "readiness": "checking", "reason": "Checking files"}
            }
        },
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/audio/runs",
            json={
                "text": "Hello",
                "engine": "fish_s2_pro",
                "voice_source": "model",
                "reference_artifact_id": None,
            },
        )
        assert response.status_code == 409 and response.json() == {"detail": "Checking files"}
    with session_factory()() as db:
        assert not list(db.scalars(select(Run)))
