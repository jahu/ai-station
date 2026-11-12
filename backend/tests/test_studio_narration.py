import hashlib
import sqlite3
import wave
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from app.api import app
from app.config import get_settings
from app.db import control_session_factory, session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Run
from app.recovery import recover_stale
from app.runs import claim_next, transition
from app.state import RunStatus
from app.studio_narration_pcm import intervals, split
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_studio_render import draft
from test_studio_soundtrack import submit, tone


def mixed(client):
    row, revision = draft(client, audio="voice_music")
    voice, score = tone(client, 1), tone(client, 3, channels=2)
    queued = submit(client, row, revision, voice, score)
    assert queued.status_code == 202, queued.text
    with control_session_factory()() as db:
        tick(db, "narration-test-mix")
    done = client.get("/api/runs/" + queued.json()["id"]).json()
    assert done["status"] == "succeeded", (done.get("error_type"), done.get("error_message"))
    return row, revision, done, voice


def request(client, row, revision_id, **extra):
    return client.post(
        f"/api/studio/materials/{row['id']}/narration",
        json={
            "client_request_id": str(uuid4()),
            "revision_id": revision_id,
            **extra,
        },
    )


def finish(client, queued):
    with session_factory()() as db:
        tick(db, "narration-test")
    return client.get("/api/runs/" + queued.json()["id"]).json()


def read(identity):
    with session_factory()() as db:
        item = db.get(Artifact, identity)
        path = get_settings().data_dir / item.relative_path
    with wave.open(str(path), "rb") as source:
        return source.getparams(), np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").reshape(
            -1, 2
        )


def test_approved_narration_retains_exact_timing_without_music_or_new_revision():
    with TestClient(app) as client:
        row, original, mix, voice = mixed(client)
        revision = mix["metadata"]["studio_revision_id"]
        assert request(client, row, original["id"]).status_code == 422
        nonce = str(uuid4())
        queued = request(client, row, revision, client_request_id=nonce)
        assert queued.status_code == 202, queued.text
        assert queued.json()["requested_gpu"] == "none"
        assert request(client, row, revision, client_request_id=nonce).json()["id"] == queued.json()["id"]
        assert request(client, row, original["id"], client_request_id=nonce).status_code == 409
        done = finish(client, queued)
        assert done["status"] == "succeeded", (done.get("error_type"), done.get("error_message"))
        metadata = done["metadata"]
        stem_id = metadata["narration_artifact_id"]
        params, clean = read(stem_id)
        assert (params.framerate, params.nchannels, params.sampwidth, params.nframes) == (
            48000,
            2,
            2,
            42 * 1600,
        )
        assert np.max(np.abs(clean[:9000])) == 0  # Same 200-ms lead-in as the mix.
        assert np.max(np.abs(clean[12000:50000])) > 10000
        assert np.max(np.abs(clean[59000:])) == 0  # No instrumental tail in the stem.
        _, soundtrack = read(mix["metadata"]["soundtrack_artifact_id"])
        assert np.max(np.abs(soundtrack[59000:64000])) > 0
        parts = metadata["parts"]
        assert len(parts) == 1 and parts[0]["duration_frames"] == 42
        assert np.array_equal(read(parts[0]["artifact_id"])[1], clean)
        result = client.get(f"/api/studio/materials/{row['id']}/narrations?revision_id={revision}").json()
        assert len(result) == 1 and len(result[0]["artifacts"]) == 2
        assert all(a["metadata"]["internal_media"] for a in result[0]["artifacts"])
        stem = client.get("/api/artifacts/" + stem_id).json()
        assert set(stem["parent_artifact_ids"]) == {voice, mix["metadata"]["soundtrack_artifact_id"]}
        assert len(client.get(f"/api/studio/materials/{row['id']}/revisions").json()) == 2


def test_parts_preserve_all_samples_across_sixty_seconds_and_pad_only_the_tiny_tail(tmp_path):
    plan = SimpleNamespace(
        frames=3601, scenes=[SimpleNamespace(duration_frames=1801), SimpleNamespace(duration_frames=1800)]
    )
    pcm = np.repeat(
        ((np.arange(plan.frames * 1600, dtype=np.int32) % 65535) - 32767).astype("<i2")[:, None], 2, axis=1
    )
    stem = tmp_path / "stem.wav"
    with wave.open(str(stem), "wb") as out:
        out.setparams((2, 2, 48000, len(pcm), "NONE", "not compressed"))
        out.writeframes(pcm.tobytes())
    parts = split(stem, plan, tmp_path)
    assert [(p["start_frame"], p["duration_frames"]) for p in parts] == [(0, 1800), (1800, 1800), (3600, 1)]
    recovered = hashlib.sha256()
    for part in parts:
        with wave.open(str(part["path"]), "rb") as source:
            assert 0.68 <= source.getnframes() / 48000 <= 60
            recovered.update(source.readframes(part["duration_frames"] * 1600))
            assert set(source.readframes(source.getnframes())) <= {0}
    assert parts[-1]["padding_samples"] == 20 * 1600
    assert recovered.hexdigest() == hashlib.sha256(pcm.tobytes()).hexdigest()
    preferred = SimpleNamespace(frames=2700, scenes=[SimpleNamespace(duration_frames=1350)] * 2)
    assert intervals(preferred) == [
        {"start_frame": 0, "duration_frames": 1350},
        {"start_frame": 1350, "duration_frames": 1350},
    ]


@pytest.mark.parametrize("failure", ["changed", "trashed"])
def test_changed_approved_cue_cannot_publish_a_stem(failure):
    with TestClient(app) as client:
        row, _, mix, voice = mixed(client)
        queued = request(client, row, mix["metadata"]["studio_revision_id"])
        with session_factory()() as db:
            cue = db.get(Artifact, voice)
            if failure == "changed":
                (get_settings().data_dir / cue.relative_path).write_bytes(b"changed source")
            else:
                cue.trashed_at = utcnow()
                db.commit()
        done = finish(client, queued)
        assert done["status"] == "failed"
        with session_factory()() as db:
            assert not list(db.scalars(select(Artifact).where(Artifact.run_id == done["id"])))


def test_account_scope_and_client_cannot_inject_sources_or_execution_controls(accounts):
    _, alice, bob = accounts
    row, _, mix, _ = mixed(alice)
    revision = mix["metadata"]["studio_revision_id"]
    assert request(bob, row, revision).status_code == 404
    assert bob.get(f"/api/studio/materials/{row['id']}/narrations?revision_id={revision}").status_code == 404
    assert request(alice, row, revision, voices={"0": str(uuid4())}).status_code == 422
    assert (
        request(
            alice, row, revision, execution_deadline_at=(utcnow() + timedelta(days=1)).isoformat()
        ).status_code
        == 422
    )


@pytest.mark.parametrize("action", ["stop", "claim", "deadline"])
def test_stop_claim_loss_and_expiry_during_pcm_work_prevent_publication(monkeypatch, action):
    from app import studio_narration

    original = studio_narration.mix
    with TestClient(app) as client:
        row, _, mix, _ = mixed(client)
        queued = request(client, row, mix["metadata"]["studio_revision_id"])
        rid = queued.json()["id"]

        def intervene(*args, **kwargs):
            result = original(*args, **kwargs)
            if action == "stop":
                response = client.post("/api/runs/" + rid + "/cancel")
                assert response.status_code == 200, response.text
            else:
                with session_factory()() as db:
                    run = db.get(Run, rid)
                    if action == "claim":
                        run.worker_id, run.claimed_at = "new-worker", utcnow()
                    else:
                        run.parameters = {
                            **run.parameters,
                            "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
                        }
                    db.commit()
            return result

        monkeypatch.setattr(studio_narration, "mix", intervene)
        done = finish(client, queued)
        assert done["status"] == ("running" if action == "claim" else "canceled"), done
        with session_factory()() as db:
            assert not list(db.scalars(select(Artifact).where(Artifact.run_id == rid)))


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_BUSY_SNAPSHOT, sqlite3.SQLITE_LOCKED])
def test_sqlite_publication_retry_reuses_pcm_and_keeps_stable_output_identities(monkeypatch, code):
    from app import studio_narration

    original, render = studio_narration.database_step_sync, studio_narration.mix
    calls, blocked = [], []

    def record(*args, **kwargs):
        calls.append(1)
        return render(*args, **kwargs)

    def retry(session, run, claim, deadline, action):
        def operation():
            value = action()
            if action.__name__ == "publish" and not blocked:
                blocked.append(1)
                error = sqlite3.OperationalError("database is locked")
                error.sqlite_errorcode = code
                raise OperationalError("publication", {}, error)
            return value

        return original(session, run, claim, deadline, operation)

    monkeypatch.setattr(studio_narration, "database_step_sync", retry)
    monkeypatch.setattr(studio_narration, "mix", record)
    with TestClient(app) as client:
        row, _, mix, _ = mixed(client)
        queued = request(client, row, mix["metadata"]["studio_revision_id"])
        done = finish(client, queued)
        assert done["status"] == "succeeded", (done.get("error_type"), done.get("error_message"))
        assert len(calls) == len(blocked) == 1
        with session_factory()() as db:
            outputs = list(db.scalars(select(Artifact).where(Artifact.run_id == done["id"])))
            assert len(outputs) == len({a.id for a in outputs}) == 2


@pytest.mark.parametrize("cancel", [False, True])
def test_stale_pcm_recovers_without_native_inspection_and_respects_stop(cancel):
    class NoNative:
        def inspect_process(self, *args):
            raise AssertionError("Pure narration must not inspect or dispatch a Host Runner process")

    with TestClient(app) as client:
        row, _, mix, _ = mixed(client)
        queued = request(client, row, mix["metadata"]["studio_revision_id"])
        rid = queued.json()["id"]
        with session_factory()() as db:
            run = claim_next(db, "gone-narration-worker")
            assert run.id == rid
            transition(db, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(db, run, RunStatus.RUNNING, event_type="executor.started")
            if cancel:
                transition(db, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
            run.lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
            assert rid in recover_stale(db, NoNative())
            db.commit()
            assert db.get(Run, rid).status == ("canceled" if cancel else "queued")
        if not cancel:
            done = finish(client, queued)
            assert done["id"] == rid and done["status"] == "succeeded", done
            assert len(done["metadata"]["parts"]) == 1
