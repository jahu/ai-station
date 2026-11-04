import io
import wave
from uuid import uuid4

import pytest
from app.api import app
from app.db import control_session_factory
from app.engine import tick
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_creative_sessions import create
from test_effects import source_video


def wav(api):
    data = io.BytesIO()
    with wave.open(data, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x20" * 24000)
    result = api.post("/api/audio/uploads", files={"file": ("tone.wav", data.getvalue(), "audio/wav")})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def manifest(video, audio=None):
    return {
        "fps": 24,
        "width": 128,
        "height": 128,
        "clips": [{"artifact_id": video, "in_frame": 0, "out_frame": 24}],
        "tracks": [{"artifact_id": audio, "duration_frames": 24}] if audio else [],
    }


def save(api, wid, value, **extra):
    return api.post(
        f"/api/timelines/{wid}/revisions",
        json={"client_request_id": str(uuid4()), "manifest": value, **extra},
    )


def test_edits_are_immutable_private_idempotent_and_explicitly_inspectable(accounts):
    admin, alice, bob = accounts
    workspace = create(alice, "timeline")
    video, audio = source_video(alice), wav(alice)
    value = manifest(video, audio)
    nonce = str(uuid4())
    first = save(alice, workspace["id"], value, client_request_id=nonce)
    assert first.status_code == 201, first.text
    assert save(alice, workspace["id"], value, client_request_id=nonce).json()["id"] == first.json()["id"]
    changed = {**value, "tracks": [{"artifact_id": audio, "duration_frames": 24, "gain": 0.3}]}
    assert save(alice, workspace["id"], changed, client_request_id=nonce).status_code == 409
    second = save(alice, workspace["id"], changed, parent_revision_id=first.json()["id"])
    assert second.status_code == 201 and second.json()["position"] == 2
    assert (
        alice.get("/api/timelines/revisions/" + first.json()["id"]).json()["manifest"]["tracks"][0]["gain"]
        == 1
    )
    assert bob.get(f"/api/timelines/{workspace['id']}/revisions").status_code == 404
    assert bob.get("/api/timelines/revisions/" + first.json()["id"]).status_code == 404
    assert bob.get("/api/timelines/sources/" + video).status_code == 404
    assert admin.get("/api/timelines/revisions/" + first.json()["id"]).status_code == 404
    assert (
        admin.get(
            "/api/timelines/revisions/" + first.json()["id"], headers={"x-ai-station-inspect-all": "true"}
        ).status_code
        == 200
    )
    assert save(bob, create(bob, "timeline")["id"], value).status_code == 422
    assert (
        alice.get(f"/api/timelines/{workspace['id']}/revisions?before=2").json()[0]["id"]
        == first.json()["id"]
    )


def test_render_binds_the_saved_edit_and_existing_creative_submission_receipt(monkeypatch):
    monkeypatch.setattr(
        "app.timelines.capabilities", lambda: {"available": True, "observation": "a" * 64, "ram_mib": 4096}
    )
    with TestClient(app) as api:
        workspace = create(api, "timeline")
        value = manifest(source_video(api))
        saved = save(api, workspace["id"], value)
        assert saved.status_code == 201, saved.text
        saved = saved.json()
        payload = {
            "client_request_id": str(uuid4()),
            "parameters": {"revision_id": saved["id"], "manifest": saved["manifest"]},
        }
        route = f"/api/creative/sessions/{workspace['id']}/generate"
        queued = api.post(route, json=payload)
        assert queued.status_code == 202, queued.text
        assert api.post(route, json=payload).json()["id"] == queued.json()["id"]
        run = queued.json()["run"]
        assert run["executor_type"] == "timeline_render" and run["requested_gpu"] == "none"
        assert run["requested_resources"] == {"ram_mib": 4096}
        assert len(run["parameters"]["sources"]) == 1
        other = create(api, "timeline")
        assert (
            api.post(
                f"/api/creative/sessions/{other['id']}/generate",
                json={**payload, "client_request_id": str(uuid4())},
            ).status_code
            == 404
        )
        changed = {
            **payload,
            "client_request_id": str(uuid4()),
            "parameters": {**payload["parameters"], "manifest": {**value, "width": 256}},
        }
        assert api.post(route, json=changed).status_code == 409
        with control_session_factory()() as db:
            from app.timelines import TimelineExecutor

            r = db.get(Run, run["id"])
            TimelineExecutor().validate_inputs(db, r)
            assert r.parameters["execution_deadline_at"]
            source = next(iter(r.parameters["sources"].values()))
            from app.config import get_settings

            (get_settings().data_dir / source["relative_path"]).write_bytes(b"changed source")
            with pytest.raises(ValueError):
                TimelineExecutor().validate_inputs(db, r)


def test_waveform_is_real_bounded_cached_private_worker_output(accounts):
    _, alice, bob = accounts
    identity = wav(alice)
    path = "/api/timelines/waveforms/" + identity
    queued = alice.post(path)
    assert queued.status_code == 202, queued.text
    assert alice.post(path).json()["id"] == queued.json()["id"]
    assert bob.post(path).status_code == 404
    with control_session_factory()() as db:
        assert tick(db, "timeline-waveform") == queued.json()["id"]
    result = alice.get("/api/runs/" + queued.json()["id"]).json()
    assert result["status"] == "succeeded", result["error_message"]
    assert result["metadata"]["waveform"]["peaks"] == [0.25] * 512
    assert result["metadata"]["waveform"]["samples"] == 24000
    assert alice.post(path).json()["id"] == queued.json()["id"]
    with control_session_factory()() as db:
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "timeline_waveform")))) == 1


def test_populated_timeline_downgrade_refuses_to_delete_saved_history(tmp_path):
    from alembic import command
    from app.db import alembic_config
    from app.models import CreativeSession, TimelineRevision
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite:///" + str(tmp_path / "timeline.sqlite"))
    with engine.begin() as connection:
        cfg = alembic_config()
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    with Session(engine) as db:
        workspace = CreativeSession(capability="timeline", title="Saved film")
        db.add(workspace)
        db.flush()
        revision = TimelineRevision(
            session_id=workspace.id,
            client_request_id=str(uuid4()),
            request_sha256="a" * 64,
            position=1,
            manifest={"private": "keep"},
            sources={},
        )
        db.add(revision)
        db.commit()
        identity = revision.id
        previous_schema = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    with pytest.raises(RuntimeError, match="Keep timeline history"):
        with engine.begin() as connection:
            cfg = alembic_config()
            cfg.attributes["connection"] = connection
            command.downgrade(cfg, "0040")
    with Session(engine) as db:
        assert db.get(TimelineRevision, identity).manifest == {"private": "keep"}
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == previous_schema
    engine.dispose()


def test_frame_progress_uses_recorded_total_and_has_no_fabricated_eta():
    from datetime import timedelta
    from types import SimpleNamespace

    from app.db import utcnow
    from app.generation_progress import parse_line, projection

    now = utcnow()
    run = SimpleNamespace(
        executor_type="timeline_render",
        parameters={"target_frames": 72},
        metadata_json={},
        status="running",
        started_at=now - timedelta(seconds=2),
        finished_at=None,
    )
    assert parse_line("timeline.frames.completed 10/100", run) is None
    progress = parse_line("timeline.frames.completed 24/72", run)
    assert progress == {"phase": "generating", "completed": 24, "total": 72, "unit": "frames"}
    run.metadata_json = {"generation_progress": {**progress, "observed_at": now.isoformat()}}
    value = projection(run, now=now)
    assert value["fraction"] == {"completed": 24, "total": 72, "unit": "frames"}
    assert value["estimate"] is None


def test_renderer_report_rejects_symlink_escape_and_oversized_bytes(tmp_path):
    from app.config import get_settings
    from app.timelines import TimelineExecutor

    path = get_settings().data_dir / "artifacts/qa-render.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.json"
    outside.write_text('{"verified": true}')
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        TimelineExecutor().output_metadata("artifacts/qa-render.mp4")
    path.unlink()
    path.write_bytes(b"x" * 32769)
    with pytest.raises(ValueError, match="bound"):
        TimelineExecutor().output_metadata("artifacts/qa-render.mp4")
