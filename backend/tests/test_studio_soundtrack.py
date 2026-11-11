import io
import wave
from uuid import uuid4

import numpy as np
import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run
from fastapi.testclient import TestClient
from test_account_private_api import accounts, private_app  # noqa: F401
from test_studio_render import draft


def tone(client, seconds, rate=24000, channels=1, extra_samples=0, amplitude=20000):
    samples = int(seconds * rate) + extra_samples
    t = np.arange(samples) / rate
    values = np.rint(np.sin(t * (2 * np.pi * 440)) * amplitude).astype("<i2")
    if channels == 2:
        values = np.repeat(values[:, None], 2, axis=1)
    data = io.BytesIO()
    with wave.open(data, "wb") as writer:
        writer.setparams((channels, 2, rate, samples, "NONE", "not compressed"))
        writer.writeframes(values.tobytes())
    result = client.post("/api/audio/uploads", files={"file": ("cue.wav", data.getvalue(), "audio/wav")})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def submit(client, row, revision, voice=None, music=None, **extra):
    return client.post(
        f"/api/studio/materials/{row['id']}/soundtrack",
        json={
            "client_request_id": str(uuid4()),
            "revision_id": revision["id"],
            "narration": [{"scene": 0, "artifact_id": voice}] if voice else [],
            "music_artifact_id": music,
            **extra,
        },
    )


def test_measured_narration_extends_the_edit_and_mix_publishes_exact_canonical_pcm(monkeypatch):
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice_music")
        voice, music = tone(client, 2), tone(client, 4, channels=2)
        nonce = str(uuid4())
        queued = submit(client, row, revision, voice, music, client_request_id=nonce)
        assert queued.status_code == 202, queued.text
        run = queued.json()
        assert run["parameters"]["storyboard"]["scenes"][0]["duration_frames"] == 72
        assert submit(client, row, revision, voice, music, client_request_id=nonce).json()["id"] == run["id"]
        assert (
            submit(client, row, revision, voice, music, client_request_id=nonce, duck=0.5).status_code == 409
        )
        with session_factory()() as session:
            tick(session, "mix-test")
        done = client.get("/api/runs/" + run["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        artifact = client.get("/api/artifacts/" + done["metadata"]["soundtrack_artifact_id"]).json()
        assert set(artifact["parent_artifact_ids"]) == {voice, music}
        assert 0 < artifact["metadata"]["peak_after"] <= 0.95
        with wave.open(str(get_settings().data_dir / artifact["relative_path"])) as reader:
            assert (
                reader.getnframes(),
                reader.getframerate(),
                reader.getnchannels(),
                reader.getsampwidth(),
            ) == (72 * 1600, 48000, 2, 2)
            pcm = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").reshape(-1, 2)
            # The complete final spoken second survives; the music-only tail is quieter.
            spoken_tail = np.max(np.abs(pcm[int(2.1 * 48000) : int(2.15 * 48000)]))
            score_tail = np.max(np.abs(pcm[int(2.3 * 48000) : int(2.35 * 48000)]))
            assert spoken_tail > 8 * score_tail > 0
            assert np.max(np.abs(pcm)) < 32767
        versions = client.get(f"/api/studio/materials/{row['id']}/revisions").json()
        assert len(versions) == 2 and versions[0]["parent_revision_id"] == revision["id"]
        assert versions[1]["storyboard"]["scenes"][0]["duration_frames"] == 30
        assert versions[0]["id"] == artifact["metadata"]["studio_revision_id"]
        from test_account_private_api import upload

        monkeypatch.setattr(
            "app.studio_render.capabilities",
            lambda: {"available": True, "ram_mib": 4352, "observation": "a" * 64},
        )
        image, _ = upload(client, "blue")
        export = client.post(
            f"/api/studio/materials/{row['id']}/render",
            json={
                "client_request_id": str(uuid4()),
                "revision_id": versions[0]["id"],
                "bindings": [{"scene": 0, "artifact_id": image}],
                "soundtrack_artifact_id": artifact["id"],
            },
        )
        assert export.status_code == 202, export.text
        assert export.json()["parameters"]["composition"]["scenes"][0]["duration_frames"] == 72


@pytest.mark.parametrize("rate", [8000, 24000, 44100, 48000, 96000])
def test_fractional_source_duration_is_resampled_without_cutting_the_spoken_tail(rate):
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice")
        voice = tone(client, 1, rate=rate, extra_samples=1)
        response = submit(client, row, revision, voice)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "mix-resample")
        done = client.get("/api/runs/" + response.json()["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        assert done["metadata"]["mix"]["samples"] == 43 * 1600


def test_missing_cues_short_score_and_silent_substitution_cannot_queue():
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice_music")
        voice, short = tone(client, 2), tone(client, 1)
        assert submit(client, row, revision, voice).status_code == 422
        assert submit(client, row, revision, None, short).status_code == 422
        response = submit(client, row, revision, voice, short)
        assert response.status_code == 422 and "cover the measured edit" in response.text
        silent, saved = draft(client)
        assert submit(client, silent, saved, voice, short).status_code == 422


def test_changed_source_fails_without_a_new_revision_or_soundtrack():
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice")
        voice = tone(client, 1)
        queued = submit(client, row, revision, voice).json()
        with session_factory()() as session:
            item = session.get(Artifact, voice)
            (get_settings().data_dir / item.relative_path).write_bytes(b"changed audio")
            tick(session, "mix-changed")
        done = client.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "failed"
        assert client.get("/api/artifacts?run_id=" + queued["id"]).json() == []
        assert len(client.get(f"/api/studio/materials/{row['id']}/revisions").json()) == 1


def test_stop_during_cpu_mixing_discards_partial_output_and_retains_previous_revision(monkeypatch):
    from app import studio_soundtrack
    from app.runs import request_cancel

    def canceled_mix(*args, check, **kwargs):
        with session_factory()() as session:
            from sqlalchemy import select

            run = session.scalar(select(Run).where(Run.executor_type == "studio_soundtrack"))
            request_cancel(session, run)
            session.commit()
        check(True)
        raise AssertionError("Cancellation must leave the mixer")

    monkeypatch.setattr(studio_soundtrack, "mix", canceled_mix)
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice")
        queued = submit(client, row, revision, tone(client, 1)).json()
        with session_factory()() as session:
            tick(session, "mix-stop")
        assert client.get("/api/runs/" + queued["id"]).json()["status"] == "canceled"
        assert client.get("/api/artifacts?run_id=" + queued["id"]).json() == []
        assert not list((get_settings().data_dir / "runs" / queued["id"]).glob("studio-pcm-*"))


def test_pcm_and_materials_remain_private(accounts):  # noqa: F811
    admin, alice, bob = accounts
    row, revision = draft(alice, audio="voice")
    foreign = tone(bob, 1)
    assert submit(alice, row, revision, foreign).status_code == 422
    for browser in (admin, bob):
        assert submit(browser, row, revision, foreign).status_code == 404


def test_lost_claim_cannot_publish_a_timed_revision_or_audio(monkeypatch):
    from app import studio_soundtrack

    def lost_claim(*args, check, **kwargs):
        from sqlalchemy import select

        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.executor_type == "studio_soundtrack"))
            run.worker_id = "replacement"
            session.commit()
        check(True)
        raise AssertionError("A replaced claim must leave the mixer")

    monkeypatch.setattr(studio_soundtrack, "mix", lost_claim)
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice")
        queued = submit(client, row, revision, tone(client, 1)).json()
        with session_factory()() as session:
            tick(session, "old-worker")
        assert client.get("/api/artifacts?run_id=" + queued["id"]).json() == []
        assert len(client.get(f"/api/studio/materials/{row['id']}/revisions").json()) == 1


def test_music_only_mix_requires_no_invented_narration_and_keeps_exact_frames():
    from test_studio_materials import board, material

    with TestClient(app) as client:
        row = material(client, options={"audio": "music"})
        saved = client.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": 1,
                "storyboard": board("music"),
            },
        )
        assert saved.status_code == 201, saved.text
        queued = submit(client, row, saved.json(), music=tone(client, 5)).json()
        with session_factory()() as session:
            tick(session, "music-only-mix")
        done = client.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        assert done["metadata"]["mix"]["samples"] == 120 * 1600
        assert done["metadata"]["mix"]["peak_after"] > 0


def test_mix_has_one_global_peak_limit_when_voice_and_score_sum_above_full_scale():
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice_music")
        queued = submit(
            client,
            row,
            revision,
            tone(client, 1, amplitude=30000),
            tone(client, 3, amplitude=30000),
            music_gain=1.0,
            duck=1.0,
            mastering_profile="none",
        ).json()
        with session_factory()() as session:
            tick(session, "peak-limit-mix")
        done = client.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        report = done["metadata"]["mix"]
        assert report["peak_before"] > 1 and 0 < report["global_gain"] < 1
        assert report["peak_after"] == pytest.approx(0.95)


def test_music_is_ducked_during_the_cue_and_recovers_between_cues():
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice_music")
        revision["storyboard"]["scenes"][0]["duration_frames"] = 120
        saved = client.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": 2,
                "parent_revision_id": revision["id"],
                "storyboard": revision["storyboard"],
            },
        ).json()
        # Silent synthetic cue isolates the music envelope; no speech model runs.
        queued = submit(client, row, saved, tone(client, 1, amplitude=0), tone(client, 4)).json()
        with session_factory()() as session:
            tick(session, "ducking-mix")
        done = client.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        artifact = client.get("/api/artifacts/" + done["metadata"]["soundtrack_artifact_id"]).json()
        with wave.open(str(get_settings().data_dir / artifact["relative_path"])) as reader:
            pcm = (
                np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
                .reshape(-1, 2)
                .astype(float)
            )
        during = np.sqrt(np.mean(pcm[24000:28800] ** 2))
        between = np.sqrt(np.mean(pcm[96000:100800] ** 2))
        assert during / between == pytest.approx(0.28, abs=0.005)


@pytest.mark.parametrize("legacy", [False, True])
def test_explicit_original_volume_and_historical_queued_requests_retain_unmastered_behavior(legacy):
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice")
        voice = tone(client, 1, amplitude=20000)
        nonce = str(uuid4())
        extra = {} if legacy else {"mastering_profile": "none"}
        response = submit(client, row, revision, voice, client_request_id=nonce, **extra)
        assert response.status_code == 202, response.text
        identity = response.json()["id"]
        with session_factory()() as db:
            run = db.get(Run, identity)
            if legacy:
                # Exact historical serialized request: no new field or policy.
                assert "mastering_profile" not in run.parameters["request"]
                run.parameters = {k: v for k, v in run.parameters.items() if k != "mastering_profile"}
                db.commit()
            tick(db, "legacy-soundtrack")
        replay = submit(client, row, revision, voice, client_request_id=nonce, **extra)
        assert replay.status_code == 202 and replay.json()["id"] == identity
        done = client.get("/api/runs/" + identity).json()
        assert done["status"] == "succeeded", done["error_message"]
        assert "mastering" not in done["metadata"]["mix"]
        # Existing equal-power mono-to-stereo upmix retains its original gain.
        assert done["metadata"]["mix"]["peak_after"] == pytest.approx(20000 / (32768 * 2**0.5), abs=0.0001)


def test_new_mix_freezes_mastering_policy_and_retains_measured_evidence():
    from app.studio_mastering import PROFILE

    with TestClient(app) as client:
        row, revision = draft(client, audio="voice")
        queued = submit(client, row, revision, tone(client, 1, amplitude=2000)).json()
        assert queued["parameters"]["mastering_profile"] == PROFILE
        with session_factory()() as db:
            tick(db, "mastered-soundtrack")
        done = client.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        report = done["metadata"]["mix"]["mastering"]
        assert report["profile"] == PROFILE and report["target_reached"]
        assert report["after"]["integrated_lufs"] == pytest.approx(-16, abs=0.5)
        assert report["after"]["true_peak_upper_dbfs"] <= -1.5
        assert report["samples"] == done["metadata"]["mix"]["samples"]


def test_stop_during_mastering_publishes_no_partial_soundtrack(monkeypatch):
    from app import studio_soundtrack
    from app.runs import request_cancel
    from sqlalchemy import select

    def stopped_master(*args, **kwargs):
        check = args[2]
        with session_factory()() as db:
            run = db.scalar(select(Run).where(Run.executor_type == "studio_soundtrack"))
            request_cancel(db, run)
            db.commit()
        check(True)
        raise AssertionError("Stop must leave the mastering stage")

    monkeypatch.setattr(studio_soundtrack, "master_wave", stopped_master)
    with TestClient(app) as client:
        row, revision = draft(client, audio="voice")
        queued = submit(client, row, revision, tone(client, 1)).json()
        with session_factory()() as db:
            tick(db, "master-stop")
        assert client.get("/api/runs/" + queued["id"]).json()["status"] == "canceled"
        assert client.get("/api/artifacts?run_id=" + queued["id"]).json() == []
        assert len(client.get(f"/api/studio/materials/{row['id']}/revisions").json()) == 1
