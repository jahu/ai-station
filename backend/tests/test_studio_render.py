import io
import json
import wave
from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Artifact, ResourceLock, Run
from app.recovery import recover_stale
from app.runner_client import RunnerError, RunnerUnavailable
from app.studio_materials import digest
from app.studio_render import RAM_MIB, StudioRenderExecutor
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts, private_app, upload  # noqa: F401
from test_studio_materials import board, material


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(
        "app.studio_render.capabilities",
        lambda: {"available": True, "ram_mib": RAM_MIB, "observation": "a" * 64},
    )


def wave_source(client, seconds=1, rate=48000, channels=2):
    data = io.BytesIO()
    with wave.open(data, "wb") as output:
        output.setsampwidth(2)
        output.setnchannels(channels)
        output.setframerate(rate)
        output.writeframes(b"\0\0" * rate * channels * seconds)
    reply = client.post("/api/audio/uploads", files={"file": ("mix.wav", data.getvalue(), "audio/wav")})
    assert reply.status_code == 201, reply.text
    return reply.json()["id"]


def draft(client, audio="silent", kind="image"):
    row = material(client, options={"audio": audio})
    value = board(
        audio,
        scenes=[
            {
                "purpose": "A clear opening",
                "duration_frames": 30,
                "visual_kind": kind,
                "visual_brief": "A prism in a narrow beam of light.",
                "narration": "Look closer." if audio != "silent" else "",
            }
        ],
    )
    response = client.post(
        f"/api/studio/materials/{row['id']}/revisions",
        json={"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": value},
    )
    assert response.status_code == 201, response.text
    return row, response.json()


def render(client, row, revision, visual=None, audio=None, **extra):
    return client.post(
        f"/api/studio/materials/{row['id']}/render",
        json={
            "client_request_id": str(uuid4()),
            "revision_id": revision["id"],
            "bindings": [{"scene": 0, "artifact_id": visual}] if visual else [],
            "soundtrack_artifact_id": audio,
            **extra,
        },
    )


def test_missing_generated_visuals_cannot_be_exported_as_a_text_template(ready):
    with TestClient(app) as client:
        row, revision = draft(client)
        response = render(client, row, revision)
        assert response.status_code == 422 and "actual media" in response.text
        image, _ = upload(client, "blue")
        row, revision = draft(client, kind="video")
        response = render(client, row, revision, image)
        assert response.status_code == 422 and "actual video" in response.text
        with session_factory()() as session:
            assert session.scalar(select(Run).where(Run.executor_type == "motion_render")) is None


def test_soundtrack_is_explicit_complete_and_canonical(ready):
    with TestClient(app) as client:
        image, _ = upload(client, "blue")
        row, revision = draft(client, audio="voice_music")
        assert render(client, row, revision, image).status_code == 422
        assert (
            render(client, row, revision, image, wave_source(client, rate=24000, channels=1)).status_code
            == 422
        )
        assert render(client, row, revision, image, wave_source(client, seconds=2)).status_code == 422
        good = render(client, row, revision, image, wave_source(client))
        assert good.status_code == 202, good.text
        assert good.json()["parameters"]["composition"]["width"] == 1080
        assert good.json()["parameters"]["composition"]["height"] == 1920
        assert good.json()["requested_resources"]["ram_mib"] == 4352
        assert good.json()["execution_target"] == "container"
        assert good.json()["requested_gpu"] == "none"


def test_export_receipt_freezes_one_request_and_source_change_fails_before_dispatch(ready):
    with TestClient(app) as client:
        image, _ = upload(client, "blue")
        row, revision = draft(client)
        nonce = str(uuid4())
        first = render(client, row, revision, image, client_request_id=nonce)
        assert first.status_code == 202, first.text
        assert (
            render(client, row, revision, image, client_request_id=nonce).json()["id"] == first.json()["id"]
        )
        assert render(client, row, revision, client_request_id=nonce).status_code == 409
        with session_factory()() as session:
            run = session.get(Run, first.json()["id"])
            original = session.get(Artifact, image)
            (get_settings().data_dir / original.relative_path).write_bytes(b"changed bytes")
            with pytest.raises(ValueError):
                StudioRenderExecutor().validate_inputs(session, run)


def test_sources_and_revisions_remain_account_scoped(ready, accounts):  # noqa: F811
    admin, alice, bob = accounts
    row, revision = draft(alice)
    foreign, _ = upload(bob, "red")
    assert render(alice, row, revision, foreign).status_code == 422
    assert render(bob, row, revision, foreign).status_code == 404
    assert render(admin, row, revision, foreign).status_code == 404


class FakeRenderer:
    def __init__(self):
        self.started = []
        self.cleanup = True
        self.unknown = False
        self.unreachable = False
        self.lost_reply = False
        self.reject = False
        self.fences = 0

    def hardware(self):
        return {"gpus": [], "memory": {"available_mib": 32000}}

    def request(self, method, path, body=None):
        if path.endswith("/cancel"):
            self.fences += 1
            return {"cleanup_confirmed": self.cleanup}
        assert (method, path) == ("POST", "/v1/runs/motion")
        if self.reject:
            raise RunnerError(409, "Start response requires fencing")
        self.started.append(body)
        root = get_settings().data_dir
        rid = body["run_id"]
        target = root / f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        # Small valid CPU fixture; this mock tests adoption/protocol, not full-HD rendering.
        import av
        import numpy as np

        with av.open(str(target), "w") as media:
            stream = media.add_stream("libx264", rate=30)
            stream.width = 64
            stream.height = 64
            stream.pix_fmt = "yuv420p"
            for _ in range(30):
                for packet in stream.encode(
                    av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), dtype=np.uint8), format="rgb24")
                ):
                    media.mux(packet)
            for packet in stream.encode():
                media.mux(packet)
        value = body["composition"]
        report = {
            "verified": True,
            "run_id": rid,
            "request_sha256": digest(body),
            "observation": body["observation"],
            "frames": 30,
            "fps": 30,
            "width": value["width"],
            "height": value["height"],
            "has_audio": bool(body["audio_artifact_id"]),
        }
        target.with_suffix(".json").write_text(json.dumps(report))
        if self.lost_reply:
            raise RunnerError(503, "Lost acknowledgement")
        return {"pid": 123, "process_group_id": 123, "runner_id": "fake"}

    def inspect_process(self, rid, **kwargs):
        if self.unreachable:
            raise RunnerUnavailable("not connected")
        if self.unknown:
            raise RunnerError(404, "not owned")
        return {
            "run_id": rid,
            "executor": "motion_render",
            "alive": False,
            "completion_pending": False,
            "status": "exited",
            "exit_code": 0,
            "cleanup_confirmed": self.cleanup,
            "stdout": "",
            "stderr": "",
            "stdout_offset": 0,
            "stderr_offset": 0,
            "stdout_more": False,
            "stderr_more": False,
        }

    def cancel_process(self, rid):
        return self.inspect_process(rid)


def test_fake_executor_api_integration_adopts_one_library_result_with_provenance(ready, monkeypatch):
    fake = FakeRenderer()
    monkeypatch.setattr(StudioRenderExecutor, "runner", lambda self, run: fake)
    with TestClient(app) as client:
        row, revision = draft(client)
        image, _ = upload(client, "blue")
        queued = render(client, row, revision, image).json()
        with session_factory()() as session:
            tick(session, "render-test")
        done = client.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        assert len(fake.started) == 1
        outputs = client.get("/api/artifacts?run_id=" + queued["id"]).json()
        assert len(outputs) == 1 and outputs[0]["type"] == "video"
        assert outputs[0]["parent_artifact_ids"] == [image]
        assert outputs[0]["metadata"]["studio_revision_id"] == revision["id"]
        assert "v1" in outputs[0]["title"]
        with session_factory()() as session:
            assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


def expired(session, rid):
    from app.resources import reserve_memory
    from app.runs import transition
    from app.state import RunStatus

    run = session.get(Run, rid)
    transition(session, run, RunStatus.CLAIMED, event_type="run.claimed")
    transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
    run.metadata_json = {"dispatch_attempted": True}
    run.worker_id = "old-worker"
    run.lease_expires_at = utcnow() - timedelta(seconds=1)
    assert reserve_memory(session, run, 32000, RAM_MIB)
    session.commit()
    return run


@pytest.mark.parametrize("case", ["unknown", "unreachable", "cleanup"])
def test_recovery_fences_missing_dispatch_and_retains_uncertain_container_resources(ready, case):
    fake = FakeRenderer()
    fake.unknown = case == "unknown"
    fake.unreachable = case == "unreachable"
    fake.cleanup = case != "cleanup"
    with TestClient(app) as client:
        row, revision = draft(client)
        image, _ = upload(client, "blue")
        queued = render(client, row, revision, image).json()
        with session_factory()() as session:
            run = expired(session, queued["id"])
            recover_stale(session, fake)
            session.commit()
            session.refresh(run)
            held = list(
                session.scalars(
                    select(ResourceLock).where(
                        ResourceLock.run_id == run.id, ResourceLock.released_at.is_(None)
                    )
                )
            )
            if case == "unknown":
                assert not held and run.status == "interrupted"
            else:
                assert held and run.status in {"preparing", "interrupted"}
        assert not fake.started


def test_polling_unconfirmed_cleanup_keeps_reservations_and_publishes_nothing(ready, monkeypatch):
    fake = FakeRenderer()
    fake.cleanup = False
    monkeypatch.setattr(StudioRenderExecutor, "runner", lambda self, run: fake)
    with TestClient(app) as client:
        row, revision = draft(client)
        image, _ = upload(client, "blue")
        queued = render(client, row, revision, image).json()
        with session_factory()() as session:
            tick(session, "render-test")
            run = session.get(Run, queued["id"], populate_existing=True)
            assert run.metadata_json.get("dispatch_attempted")
            assert not run.metadata_json.get("process_confirmed_gone")
            recover_stale(session, fake)
            session.commit()
            assert run.status == "interrupted"
            assert session.scalar(
                select(ResourceLock).where(ResourceLock.run_id == run.id, ResourceLock.released_at.is_(None))
            )
        assert client.get("/api/artifacts?run_id=" + queued["id"]).json() == []


def test_lost_start_reply_resumes_collection_without_repeating_render(ready, monkeypatch):
    fake = FakeRenderer()
    fake.lost_reply = True
    monkeypatch.setattr(StudioRenderExecutor, "runner", lambda self, run: fake)
    with TestClient(app) as client:
        row, revision = draft(client)
        image, _ = upload(client, "blue")
        queued = render(client, row, revision, image).json()
        with session_factory()() as session:
            tick(session, "render-test")
            run = session.get(Run, queued["id"], populate_existing=True)
            assert run.status == "preparing"
            recover_stale(session, fake)
            session.commit()
            assert run.status == "queued" and run.metadata_json["media_inspection_resume"]
            tick(session, "replacement-worker")
        done = client.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        assert len(fake.started) == 1


def test_rejected_missing_dispatch_is_fenced_before_resource_release(ready, monkeypatch):
    fake = FakeRenderer()
    fake.reject = fake.unknown = True
    monkeypatch.setattr(StudioRenderExecutor, "runner", lambda self, run: fake)
    with TestClient(app) as client:
        row, revision = draft(client)
        image, _ = upload(client, "blue")
        queued = render(client, row, revision, image).json()
        with session_factory()() as session:
            tick(session, "render-test")
            run = session.get(Run, queued["id"], populate_existing=True)
            assert run.status == "failed"
            assert not session.scalar(
                select(ResourceLock).where(ResourceLock.run_id == run.id, ResourceLock.released_at.is_(None))
            )
        assert fake.fences == 1 and not fake.started
