"""Actual worker/SQL lifecycle with explicitly fake native media and processes."""

import hashlib
import json
import time
from datetime import timedelta

import pytest
from app import host_media_executor
from app.config import get_settings
from app.db import utcnow
from app.dependencies import depend_on
from app.engine import tick
from app.generation_progress import parse_line
from app.models import Artifact, ResourceLock
from app.recovery import recover_stale
from app.runs import create_run
from app.svi_executor import GEOMETRY, NAME, RAM_MIB, SviExecutor
from sqlalchemy import select
from test_svi_executor import owned_pair  # noqa: F401 -- shared fixture


class FakeNative:
    def __init__(self):
        self.starts = []
        self.records = {}
        self.pending = False

    def hardware(self):
        return {"memory": {"available_mib": 30000}, "gpus": [{"index": 7, "memory_total_mib": 12288}]}

    def request(self, method, path, payload):
        assert (method, path) == ("POST", "/v1/runs/svi")
        self.starts.append(payload)
        identity = payload["run_id"]
        root = get_settings().data_dir
        relative = f"artifacts/{identity[:2]}/{identity[2:4]}/{identity}"
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        video, motion = b"fake generated video", b"fake bounded motion"
        (root / (relative + ".mp4")).write_bytes(video)
        (root / (relative + ".safetensors")).write_bytes(motion)
        (root / (relative + ".json")).write_text(
            json.dumps(
                {
                    **GEOMETRY,
                    "backend": "wan22-svi-pro-q4",
                    "profile_identity": "c" * 64,
                    "managed_runtime": payload["managed_runtime"],
                    "output_sha256": hashlib.sha256(video).hexdigest(),
                    "motion_context": {
                        "relative_path": relative + ".safetensors",
                        "sha256": hashlib.sha256(motion).hexdigest(),
                        "size_bytes": len(motion),
                    },
                }
            )
        )
        self.records[identity] = {
            "run_id": identity,
            "executor": NAME,
            "pid": 1234,
            "process_group_id": 1234,
            "runner_id": "fake",
            "started_at": time.time(),
            "deadline_at": payload["deadline_at"],
            "alive": self.pending,
            "status": "running" if self.pending else "exited",
            "exit_code": None if self.pending else 0,
            "stdout": "video.stage: sampling high expert\n",
            "stderr_tail": "",
            "stderr": "",
            "stdout_more": False,
            "stderr_more": False,
            "stdout_offset": 1,
            "stderr_offset": 0,
        }
        return self.records[identity]

    def inspect_process(self, identity, **offsets):
        return dict(self.records[identity])

    def cancel_process(self, identity):
        self.records[identity].update(alive=False, status="canceled", exit_code=-15)
        return dict(self.records[identity])


def test_two_dependent_windows_use_same_source_collect_motion_and_release_all_locks(
    session, pair, monkeypatch
):
    fake = FakeNative()
    adapter = SviExecutor()
    monkeypatch.setattr(adapter, "runner", lambda _: fake)
    values = {key: value for key, value in pair.current.parameters.items() if key != "previous_motion_run_id"}
    second = create_run(
        session,
        pair.current.task,
        run_type="video",
        capability="video.animate",
        executor_type=NAME,
        parameters={**values, "previous_motion_run_id": pair.current.id, "seed": 234},
        requested_resources={"ram_mib": RAM_MIB},
        requested_gpu="auto",
        permissions=["filesystem_read", "workspace_write"],
    )
    depend_on(session, second, pair.current)
    session.commit()
    assert tick(session, "svi-first", executors={NAME: adapter}, runner=fake) == pair.current.id
    assert pair.current.status == "succeeded"
    assert tick(session, "svi-second", executors={NAME: adapter}, runner=fake) == second.id
    assert second.status == "succeeded"
    assert len(fake.starts) == 2
    assert fake.starts[0]["image"] == fake.starts[1]["image"]
    video = session.scalar(
        select(Artifact).where(Artifact.run_id == pair.current.id, Artifact.artifact_type == "video")
    )
    motion = session.get(Artifact, video.metadata_json["motion_context_artifact_id"])
    assert fake.starts[1]["previous_motion"]["sha256"] == motion.sha256
    assert motion.metadata_json["context_frames"] == 4 and motion.metadata_json["internal_media"]
    assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


@pytest.mark.parametrize("cancel", [False, True])
def test_expired_worker_lease_resumes_inspection_without_relaunch_and_honors_stop(
    session, pair, monkeypatch, cancel
):
    fake = FakeNative()
    fake.pending = True
    adapter = SviExecutor()
    monkeypatch.setattr(adapter, "runner", lambda _: fake)
    poll = adapter._poll
    monkeypatch.setattr(adapter, "_poll", lambda *args: None)
    monkeypatch.setattr(host_media_executor, "RESUMABLE_MEDIA", host_media_executor.RESUMABLE_MEDIA | {NAME})
    session.commit()
    assert tick(session, "svi-old-worker", executors={NAME: adapter}, runner=fake) == pair.current.id
    assert pair.current.status == "running"
    native_identity = dict(fake.records[pair.current.id])
    pair.current.lease_expires_at = utcnow() - timedelta(seconds=1)
    if cancel:
        pair.current.status = "cancel_requested"
        pair.current.cancellation_requested_at = utcnow()
    else:
        fake.records[pair.current.id].update(alive=False, status="exited", exit_code=0)
    session.commit()
    recover_stale(session, fake)
    session.commit()
    assert pair.current.metadata_json["media_inspection_resume"]
    monkeypatch.setattr(adapter, "_poll", poll)
    assert tick(session, "svi-new-worker", executors={NAME: adapter}, runner=fake) == pair.current.id
    assert pair.current.status == ("canceled" if cancel else "succeeded")
    assert len(fake.starts) == 1
    for key in ("pid", "process_group_id", "started_at", "deadline_at"):
        assert fake.records[pair.current.id][key] == native_identity[key]
    if cancel:
        assert not list(session.scalars(select(Artifact).where(Artifact.run_id == pair.current.id)))
    assert not list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


def test_progress_keeps_two_expert_bars_separate_from_job_completion():
    from types import SimpleNamespace

    run = SimpleNamespace(executor_type=NAME, parameters={"steps": 20})
    assert parse_line("video.stage: sampling high expert", run) == {"phase": "generating"}
    assert parse_line("video.stage: loading low expert", run) == {"phase": "generating"}
    assert parse_line("100%|########|9/9 [21:52<00:00,145.8s/it]", run) is None
    assert parse_line("100%|########|11/11 [26:44<00:00,145.8s/it]", run) is None
    assert parse_line("video.stage: decoding frames", run) == {"phase": "finishing"}
