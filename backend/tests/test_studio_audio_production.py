import io
import tempfile
import wave
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.api import app
from app.artifacts import register_file
from app.db import session_factory, utcnow
from app.engine import tick
from app.executors import EXECUTORS
from app.models import Artifact, Run
from app.recovery import recover_stale
from app.runs import create_run, transition
from app.state import TERMINAL, RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts, private_app  # noqa: F401
from test_studio_render import draft


class FakeAudio:
    def execute(self, session, run):
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        data = io.BytesIO()
        with wave.open(data, "wb") as writer:
            writer.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            writer.writeframes(b"\0\0" * 24000 * run.parameters["seconds"])
        with tempfile.NamedTemporaryFile(suffix=".wav") as temporary:
            temporary.write(data.getvalue())
            temporary.flush()
            register_file(
                session,
                source=Path(temporary.name),
                artifact_type="audio",
                mime_type="audio/wav",
                original_filename="synthetic.wav",
                run_id=run.id,
            )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


@pytest.fixture
def generators(monkeypatch):
    from app import studio_audio_production as production

    speech, music = [], []

    def voice(session, body, *, task, parent_run_id):
        speech.append(body.model_dump(mode="json"))
        return create_run(
            session,
            task,
            run_type="audio",
            capability="audio.speech",
            executor_type="synthetic_speech",
            execution_target="container",
            parent_run_id=parent_run_id,
            parameters={"seconds": 8, "text": body.text},
            permissions=["filesystem_read", "workspace_write"],
        )

    def score(session, body, *, task, parent_run_id):
        music.append(body.model_dump(mode="json"))
        return create_run(
            session,
            task,
            run_type="audio",
            capability="audio.music",
            executor_type="synthetic_music",
            execution_target="container",
            parent_run_id=parent_run_id,
            parameters={"seconds": body.duration_seconds},
            permissions=["filesystem_read", "workspace_write"],
        )

    monkeypatch.setattr(production, "create_audio_run", voice)
    monkeypatch.setattr(production, "create_music_run", score)
    return speech, music, {**EXECUTORS, "synthetic_speech": FakeAudio(), "synthetic_music": FakeAudio()}


def submit(client, row, revision, **extra):
    return client.post(
        f"/api/studio/materials/{row['id']}/audio/produce",
        json={
            "client_request_id": str(uuid4()),
            "revision_id": revision["id"],
            **extra,
        },
    )


def two_shots(client):
    row, revision = draft(client, audio="voice_music")
    revision["storyboard"]["scenes"].append(
        {**revision["storyboard"]["scenes"][0], "narration": "The next piece of the story."}
    )
    saved = client.post(
        f"/api/studio/materials/{row['id']}/revisions",
        json={
            "client_request_id": str(uuid4()),
            "expected_version": 2,
            "parent_revision_id": revision["id"],
            "storyboard": revision["storyboard"],
        },
    )
    assert saved.status_code == 201, saved.text
    return row, saved.json()


def test_durable_chain_preserves_narrator_measures_speech_and_generates_a_covering_score(generators):
    speech, music, executors = generators
    with TestClient(app) as client:
        row, revision = two_shots(client)
        nonce = str(uuid4())
        first = submit(client, row, revision, client_request_id=nonce)
        assert first.status_code == 202, first.text
        queued = first.json()
        assert submit(client, row, revision, client_request_id=nonce).json()["id"] == queued["id"]
        assert submit(client, row, revision).status_code == 409
        with session_factory()() as session:
            for _ in range(20):
                tick(session, "studio-audio", executors=executors)
                runs = list(session.scalars(select(Run).where(Run.task_id == queued["task_id"])))
                if all(r.status in TERMINAL for r in runs):
                    break
            assert all(r.status == "succeeded" for r in runs), [
                (r.executor_type, r.status, r.error_message) for r in runs
            ]
            audio = list(
                session.scalars(
                    select(Artifact).where(
                        Artifact.run_id.in_([r.id for r in runs]), Artifact.artifact_type == "audio"
                    )
                )
            )
        assert len(speech) == 2 and len(music) == 1
        assert speech[0]["voice_source"] == "model" and speech[0]["reference_artifact_id"] is None
        assert speech[1].get("voice_source", "reference") == "reference"
        assert speech[1]["reference_artifact_id"] in {a.id for a in audio}
        assert music[0]["duration_seconds"] == 17 and music[0]["instrumental"] is True
        mixes = [a for a in audio if a.metadata_json.get("profile") == "studio-pcm48-v1"]
        assert len(mixes) == 1 and mixes[0].metadata_json["samples"] == (8 * 30 + 12) * 2 * 1600
        assert len(client.get(f"/api/studio/materials/{row['id']}/revisions").json()) == 3
        status = client.get(
            f"/api/studio/materials/{row['id']}/audio/productions?revision_id={mixes[0].metadata_json['studio_revision_id']}"
        )
        assert status.status_code == 200 and status.json()[0]["status"] == "succeeded"
        assert status.json()[0]["soundtrack"]["id"] == mixes[0].id


def test_stop_cancels_the_whole_audio_task_and_retains_completed_cues(generators):
    speech, music, executors = generators
    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as session:
            tick(session, "audio-stop", executors=executors)
            tick(session, "audio-stop", executors=executors)
        reply = client.post(f"/api/studio/materials/{row['id']}/audio/{root['id']}/stop")
        assert reply.status_code == 200, reply.text
        with session_factory()() as session:
            runs = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(r.status in {"succeeded", "canceled"} for r in runs)
            assert (
                len(list(session.scalars(select(Artifact).where(Artifact.run_id.in_([r.id for r in runs])))))
                == 1
            )
        assert len(speech) == 1 and not music


def test_stale_queue_only_step_is_recovered_without_replaying_speech(generators):
    speech, music, executors = generators
    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as session:
            run = session.get(Run, root["id"])
            for status in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
                transition(session, run, status, event_type="qa.fixture")
            run.worker_id = "dead"
            run.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
            recover_stale(session)
            session.commit()
            assert run.status == "queued" and run.worker_id is None
            tick(session, "replacement", executors=executors)
            tick(session, "replacement", executors=executors)
            assert len(speech) == 1 and not music


def test_private_materials_and_voice_configuration_are_validated(accounts):  # noqa: F811
    admin, alice, bob = accounts
    row, revision = two_shots(alice)
    for browser in (admin, bob):
        assert submit(browser, row, revision).status_code == 404
    assert submit(alice, row, revision, voice={"engine": "chatterbox"}).status_code == 422
    assert submit(alice, row, revision, music_caption="x" * 513).status_code == 422
    assert submit(alice, row, revision, voice={"engine": "external"}).status_code == 422


def test_recovery_after_first_cue_observes_its_artifact_instead_of_regenerating_it(generators):
    speech, music, executors = generators
    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as session:
            tick(session, "first-worker", executors=executors)
            tick(session, "first-worker", executors=executors)
            step = session.scalar(
                select(Run).where(
                    Run.task_id == root["task_id"],
                    Run.executor_type == "studio_audio_step",
                    Run.status == "queued",
                )
            )
            for status in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
                transition(session, step, status, event_type="qa.fixture")
            step.worker_id = "dead"
            step.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
            recover_stale(session)
            session.commit()
            tick(session, "replacement", executors=executors)
        assert len(speech) == 2 and not music
        assert speech[1]["reference_artifact_id"] is not None


def test_failed_voice_blocks_later_generation_and_retains_actual_failure(generators):
    speech, music, executors = generators

    class Failed:
        def execute(self, session, run):
            from app.runs import mark_failed

            mark_failed(session, run, "SyntheticFailure", "Voice fixture failed")
            return "done"

    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as session:
            for _ in range(5):
                tick(session, "failed-voice", executors={**executors, "synthetic_speech": Failed()})
            runs = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert any(r.error_type == "SyntheticFailure" for r in runs)
            assert any(r.error_type == "PrerequisiteFailed" for r in runs)
            assert not list(
                session.scalars(select(Artifact).where(Artifact.run_id.in_([r.id for r in runs])))
            )
        assert len(speech) == 1 and not music


def test_revoked_step_permissions_cannot_publish_generation_work(generators):
    speech, music, executors = generators
    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as session:
            run = session.get(Run, root["id"])
            run.effective_permissions = ["filesystem_read"]
            session.commit()
            tick(session, "revoked", executors=executors)
        assert not speech and not music
        assert client.get("/api/runs/" + root["id"]).json()["status"] == "failed"


def test_delivery_choices_come_from_the_structured_director_plan(generators):
    speech, music, executors = generators
    with TestClient(app) as client:
        row, revision = two_shots(client)
        revision["storyboard"]["narration_delivery"] = {"direction": "whisper", "pace": "slow"}
        saved = client.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": 3,
                "parent_revision_id": revision["id"],
                "storyboard": revision["storyboard"],
            },
        ).json()
        root = submit(client, row, saved).json()
        assert root["parameters"]["request"]["voice"]["direction"] == "whisper"
        with session_factory()() as session:
            tick(session, "directed", executors=executors)
        assert speech[0]["direction"] == "whisper" and speech[0]["pace"] == "slow"


def test_production_status_remains_private(accounts, generators):  # noqa: F811
    _, alice, bob = accounts
    _, _, executors = generators
    row, revision = two_shots(alice)
    root = submit(alice, row, revision).json()
    url = f"/api/studio/materials/{row['id']}/audio/productions?revision_id={revision['id']}"
    current = alice.get(url)
    assert current.status_code == 200 and current.json()[0]["status"] == "running"
    assert bob.get(url).status_code == 404
    assert bob.post(f"/api/studio/materials/{row['id']}/audio/{root['id']}/stop").status_code == 404
    # Actual account worker dispatch is qualified by the shared engine tests;
    # this private route test deliberately stops before any generated media.


def test_measured_audio_edit_retains_real_takes_but_a_rewritten_shot_does_not():
    from test_account_private_api import upload
    from test_studio_soundtrack import submit as mix_request
    from test_studio_soundtrack import tone

    with TestClient(app) as client:
        row, revision = draft(client, audio="voice")
        take = client.post(
            f"/api/studio/materials/{row['id']}/shots",
            json={
                "client_request_id": str(uuid4()),
                "revision_id": revision["id"],
                "scene": 0,
            },
        ).json()
        image, _ = upload(client, "blue")
        with session_factory()() as session:
            session.get(Run, take["id"]).status = "succeeded"
            session.get(Artifact, image).run_id = take["id"]
            session.commit()
        queued = mix_request(client, row, revision, tone(client, 2)).json()
        with session_factory()() as session:
            tick(session, "lineage-mix")
        done = client.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        measured = done["metadata"]["studio_revision_id"]
        production = client.get(f"/api/studio/materials/{row['id']}/revisions/{measured}/production").json()
        assert [a["id"] for a in production["artifacts"]] == [image]
        saved = client.get(f"/api/studio/materials/{row['id']}/revisions/{measured}").json()
        saved["storyboard"]["scenes"][0]["visual_brief"] = "An entirely new visual composition"
        current = client.get(f"/api/studio/materials/{row['id']}").json()
        rewritten = client.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": current["version"],
                "parent_revision_id": measured,
                "storyboard": saved["storyboard"],
            },
        ).json()
        assert (
            client.get(f"/api/studio/materials/{row['id']}/revisions/{rewritten['id']}/production").json()[
                "artifacts"
            ]
            == []
        )


def long_first_cue(monkeypatch):
    from app import studio_audio_production as production

    original = production.create_audio_run
    calls = []

    def create(session, body, **kwargs):
        run = original(session, body, **kwargs)
        calls.append(run.id)
        if len(calls) == 1:
            run.parameters = {**run.parameters, "seconds": 65}
        return run

    monkeypatch.setattr(production, "create_audio_run", create)


def test_long_first_passage_uses_a_short_voice_reference_without_cutting_narration(generators, monkeypatch):
    speech, _, executors = generators
    long_first_cue(monkeypatch)
    with TestClient(app) as client:
        row, revision = two_shots(client)
        root = submit(client, row, revision).json()
        with session_factory()() as session:
            for _ in range(25):
                tick(session, "long-narrator", executors=executors)
                runs = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
                if all(r.status in TERMINAL for r in runs):
                    break
            assert all(r.status == "succeeded" for r in runs), [
                (r.executor_type, r.status, r.error_message) for r in runs
            ]
            sampled = session.scalar(
                select(Artifact).where(
                    Artifact.run_id.in_([r.id for r in runs if r.executor_type == "studio_voice_reference"])
                )
            )
            assert sampled is not None and sampled.metadata_json["internal_media"] is True
            assert sampled.metadata_json["duration_seconds"] == 15
            assert speech[1]["reference_artifact_id"] == sampled.id
            original = session.get(Artifact, sampled.parent_artifact_ids[0])
            from app.studio_soundtrack import audio_source

            observed = audio_source(session, original.id)
            assert observed["samples"] == 65 * observed["sample_rate"]
            mixed = next(r for r in runs if r.executor_type == "studio_soundtrack")
            assert mixed.parameters["voices"]["0"]["artifact_id"] == original.id
            assert mixed.parameters["storyboard"]["scenes"][0]["duration_frames"] == 65 * 30 + 12


def test_stop_while_sampling_voice_publishes_no_reference_or_later_generation(generators, monkeypatch):
    from app.task_control import cancel_task

    speech, music, executors = generators
    long_first_cue(monkeypatch)
    read = wave.Wave_read.readframes
    stopped = []

    def interrupt(reader, frames):
        data = read(reader, frames)
        if frames == 16384 and not stopped:
            with session_factory()() as peer:
                run = peer.scalar(
                    select(Run).where(Run.executor_type == "studio_voice_reference", Run.status == "running")
                )
                if run:
                    cancel_task(peer, run.task)
                    peer.commit()
                    stopped.append(run.id)
        return data

    monkeypatch.setattr(wave.Wave_read, "readframes", interrupt)
    with TestClient(app) as client:
        row, revision = two_shots(client)
        assert submit(client, row, revision).status_code == 202
        with session_factory()() as session:
            for _ in range(12):
                tick(session, "reference-stop", executors=executors)
            assert stopped and session.get(Run, stopped[0]).status == "canceled"
            assert not list(session.scalars(select(Artifact).where(Artifact.run_id == stopped[0])))
            from app.config import get_settings

            assert not list((get_settings().data_dir / "runs" / stopped[0]).glob("voice-reference-*"))
        assert len(speech) == 1 and not music


def test_oversized_selected_narrator_is_rejected_before_queueing(generators, monkeypatch):
    _, _, executors = generators
    long_first_cue(monkeypatch)
    with TestClient(app) as client:
        first, revision = two_shots(client)
        queued = submit(client, first, revision).json()
        with session_factory()() as session:
            tick(session, "long-recording", executors=executors)
            tick(session, "long-recording", executors=executors)
            recording = session.scalar(
                select(Artifact.id)
                .join(Run, Artifact.run_id == Run.id)
                .where(Run.task_id == queued["task_id"])
            )
        row, revision = two_shots(client)
        response = submit(client, row, revision, voice={"reference_artifact_id": recording})
        assert response.status_code == 422 and "0.1–60 seconds" in response.json()["detail"]
        with session_factory()() as session:
            assert not list(
                session.scalars(
                    select(Run).where(Run.parameters["studio_material_id"].as_string() == row["id"])
                )
            )


def test_replaced_reference_claim_cannot_publish_or_cancel_the_new_owner(generators, monkeypatch):
    from app.config import get_settings

    _, _, executors = generators
    long_first_cue(monkeypatch)
    read = wave.Wave_read.readframes
    replaced = []

    def replace(reader, frames):
        data = read(reader, frames)
        if frames == 16384 and not replaced:
            with session_factory()() as peer:
                run = peer.scalar(
                    select(Run).where(Run.executor_type == "studio_voice_reference", Run.status == "running")
                )
                if run:
                    run.worker_id = "replacement"
                    run.claimed_at = utcnow()
                    run.lease_expires_at = utcnow() + timedelta(seconds=45)
                    peer.commit()
                    replaced.append(run.id)
        return data

    monkeypatch.setattr(wave.Wave_read, "readframes", replace)
    with TestClient(app) as client:
        row, revision = two_shots(client)
        assert submit(client, row, revision).status_code == 202
        with session_factory()() as session:
            for _ in range(4):
                tick(session, "reference-original", executors=executors)
            assert replaced
            run = session.get(Run, replaced[0])
            session.refresh(run)
            assert run.worker_id == "replacement" and run.status == "running"
            assert not list(session.scalars(select(Artifact).where(Artifact.run_id == run.id)))
            assert not list((get_settings().data_dir / "runs" / run.id).glob("voice-reference-*"))


def test_legacy_audio_coordination_keeps_original_mix_policy(generators):
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice_music")
        queued = submit(client, row, revision).json()
        with session_factory()() as db:
            root = db.get(Run, queued["id"])
            assert root.parameters["mastering_profile"] == "studio-lufs16-v1"
            root.parameters = {k: v for k, v in root.parameters.items() if k != "mastering_profile"}
            db.commit()
            for _ in range(20):
                if tick(db, "legacy-audio-policy", executors=generators[2]) is None:
                    break
            mixed = db.scalar(select(Run).where(Run.executor_type == "studio_soundtrack"))
            assert mixed and mixed.status == "succeeded", mixed.error_message if mixed else "missing mix"
            assert mixed.parameters.get("mastering_profile") is None
            assert "mastering" not in mixed.metadata_json["mix"]
