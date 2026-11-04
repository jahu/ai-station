"""Busy persistence and lost workers never replay owned media generation."""

import sqlite3
import threading
import time
from datetime import timedelta

import pytest
from app.config import get_settings
from app.db import utcnow
from app.engine import tick
from app.events import list_events
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact, ResourceLock, Run
from app.recovery import recover_stale
from app.runs import create_run, create_task, request_cancel, transition
from PIL import Image
from sqlalchemy import select


class Media(HostMediaExecutor):
    requires_gpu = False

    def __init__(self, kind):
        self.name = "photo_pipe" if kind == "image" else "wan_video"
        self.artifact_type = kind
        self.mime_type = "image/png" if kind == "image" else "video/mp4"
        self.suffix = ".png" if kind == "image" else ".mp4"
        self.starts = 0
        self.inspections = 0
        self.cancels = 0
        self.status = "exited"
        self.output = None
        self.inspect_hook = None

    def runner(self, run):
        self.run_id = run.id
        return self

    def _start(self, runner, run, allocated, output):
        self.starts += 1
        self.write_output(run, output)
        return self.inspect_process(run.id)

    def write_output(self, run, output=None):
        self.run_id = run.id
        output = output or f"artifacts/{run.id[:2]}/{run.id[2:4]}/{run.id}{self.suffix}"
        self.output = get_settings().data_dir / output
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.artifact_type == "image":
            Image.new("RGB", (32, 32), "blue").save(self.output)
        else:
            self.output.write_bytes(b"synthetic owned video result")

    def inspect_process(self, run_id, **offsets):
        self.inspections += 1
        if self.inspect_hook and offsets:
            self.inspect_hook()
        assert run_id == self.run_id
        return {
            "run_id": run_id,
            "executor": self.name,
            "alive": self.status == "running",
            "status": self.status,
            "exit_code": 0,
            "pid": 123,
            "stdout": "owned result\n" if not offsets.get("stdout_offset") else "",
            "stderr": "",
            "stdout_offset": 13,
            "stderr_offset": 0,
            "stdout_more": False,
            "stderr_more": False,
        }

    def cancel_process(self, run_id):
        assert run_id == self.run_id
        self.cancels += 1
        self.status = "canceled"


def enqueue(session, media):
    run = create_run(
        session,
        create_task(session, title="Media regression", prompt="", capability="test"),
        run_type="test",
        capability="test",
        executor_type=media.name,
        permissions=["filesystem_read", "workspace_write"],
    )
    session.commit()
    return run


@pytest.mark.parametrize("kind", ["image", "video"])
def test_actual_sqlite_contention_during_poll_retains_result_and_single_dispatch(session, kind, caplog):
    media = Media(kind)
    run = enqueue(session, media)
    # Use a real second SQLite writer and a short timeout, not a mocked error.
    session.connection().exec_driver_sql("PRAGMA busy_timeout=20")
    session.commit()
    threads = []

    def contend_once():
        if threads:
            return
        acquired = threading.Event()

        def writer():
            with sqlite3.connect(session.bind.url.database) as other:
                other.execute("BEGIN IMMEDIATE")
                acquired.set()
                time.sleep(0.3)
                other.rollback()

        thread = threading.Thread(target=writer)
        threads.append(thread)
        thread.start()
        assert acquired.wait(2), "Runner inspection must not hold the SQLite writer"

    media.inspect_hook = contend_once
    try:
        tick(session, "worker", executors={media.name: media})
    finally:
        for thread in threads:
            thread.join(3)
    session.refresh(run)
    assert run.status == "succeeded" and media.starts == 1
    assert "retaining owned media inspection" in caplog.text
    events = list_events(session, run.id)
    assert [e.payload["text"] for e in events if e.event_type == "stdout"] == ["owned result\n"]
    assert len(list(session.scalars(select(Artifact).where(Artifact.run_id == run.id)))) == 1
    assert not run.error_message


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("cancel", [False, True])
def test_stale_owned_media_reclaims_inspection_and_result_without_restart(session, monkeypatch, kind, cancel):
    media = Media(kind)
    run = enqueue(session, media)
    run.worker_id = "gone"
    run.claimed_at = utcnow() - timedelta(minutes=3)
    transition(session, run, "claimed", event_type="run.claimed")
    transition(session, run, "preparing", event_type="executor.preparing")
    transition(session, run, "running", event_type="executor.started")
    run.lease_expires_at = utcnow() - timedelta(seconds=1)
    run.metadata_json = {"dispatch_attempted": True}
    lock = ResourceLock(resource_key="gpu:7", run_id=run.id)
    session.add(lock)
    media.write_output(run)
    session.commit()
    assert recover_stale(session, runner=media) == [run.id]
    session.commit()
    assert run.status == "queued" and run.metadata_json["media_inspection_resume"]
    assert lock.released_at is None
    if cancel:
        # Stop during the queued inspection handoff must still cancel the native job.
        media.status = "running"
        request_cancel(session, run)
        session.commit()
        assert run.status == "queued"
    from app.photo_executor import PhotoPipeExecutor
    from app.video import VideoExecutor

    adapter = PhotoPipeExecutor() if kind == "image" else VideoExecutor()
    monkeypatch.setattr(adapter, "runner", lambda run: media)

    def forbidden(*args):
        raise AssertionError("An inspection handoff must never start inference again")

    monkeypatch.setattr(adapter, "_start", forbidden)
    tick(session, "replacement", executors={media.name: adapter}, runner=media)
    session.refresh(run)
    session.refresh(lock)
    assert run.status == ("canceled" if cancel else "succeeded")
    assert media.starts == 0 and media.cancels == int(cancel)
    assert lock.released_at is not None
    artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == run.id)))
    assert len(artifacts) == (0 if cancel else 1)


def test_old_poll_cannot_complete_a_replaced_claim(session):
    media = Media("image")
    run = enqueue(session, media)
    run.status = "running"
    run.worker_id = "old"
    run.claimed_at = utcnow()
    session.commit()
    old_claim = (run.worker_id, run.claimed_at)
    run.worker_id = "replacement"
    session.commit()
    called = []
    assert not media._database_step(session, run, old_claim, lambda: called.append(True))
    assert not called


@pytest.mark.parametrize("phase", ["stdout", "completion"])
def test_busy_flush_or_completion_rolls_back_without_lost_logs_or_duplicate_result(
    session, monkeypatch, phase
):
    from app import host_media_executor
    from sqlalchemy.exc import OperationalError

    media = Media("image")
    run = enqueue(session, media)
    failed = False
    original_append = host_media_executor.append_event
    original_commit = session.commit

    def busy():
        nonlocal failed
        failed = True
        original = sqlite3.OperationalError("synthetic busy")
        original.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise OperationalError("fixture", {}, original)

    def append(current, identity, kind, payload):
        result = original_append(current, identity, kind, payload)
        if phase == "stdout" and kind == "stdout" and not failed:
            busy()
        return result

    def commit():
        if phase == "completion" and run.status == "succeeded" and not failed:
            busy()
        original_commit()

    monkeypatch.setattr(host_media_executor, "append_event", append)
    monkeypatch.setattr(session, "commit", commit)
    tick(session, "worker", executors={media.name: media})
    session.refresh(run)
    assert failed and run.status == "succeeded" and media.starts == 1
    assert len(list(session.scalars(select(Artifact).where(Artifact.run_id == run.id)))) == 1
    kinds = [e.event_type for e in list_events(session, run.id)]
    assert kinds.count("stdout") == kinds.count("run.completed") == 1


@pytest.mark.parametrize("kind", ["image", "video"])
def test_confirmed_exit_with_missing_output_fails_once_instead_of_inspection_loop(session, kind):
    media = Media(kind)
    run = enqueue(session, media)
    original_start = media._start

    def start(*args):
        result = original_start(*args)
        media.output.unlink()
        return result

    media._start = start
    tick(session, "worker", executors={media.name: media})
    session.refresh(run)
    assert run.status == "failed" and run.error_type == "FileNotFoundError"
    assert run.metadata_json["process_confirmed_gone"]
    assert media.starts == 1
    assert recover_stale(session, runner=media) == []


def test_inspection_handoff_keeps_result_in_original_account(session, monkeypatch):
    from app.accounts import bootstrap_admin, create_user, login
    from app.data_access import DataScope, ScopedSession
    from app.db import get_engine
    from app.photo_executor import PhotoPipeExecutor

    bootstrap_admin(session, "Owner", "synthetic owner password", local_setup=True)
    grant = login(session, "Owner", "synthetic owner password")
    alice = create_user(session, grant.principal, "Alice", "synthetic user password")
    bob = create_user(session, grant.principal, "Bob", "synthetic user password")
    owner, other_owner = alice.id, bob.id
    session.commit()
    media = Media("image")
    with ScopedSession(
        bind=get_engine(), scope=DataScope(owner, execution=True), expire_on_commit=False
    ) as owned:
        run = enqueue(owned, media)
        identity = run.id
        run.status = "running"
        run.worker_id = "lost-owner-worker"
        run.claimed_at = utcnow()
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        run.metadata_json = {"dispatch_attempted": True}
        media.write_output(run)
        owned.commit()
    recover_stale(session, runner=media)
    session.commit()
    adapter = PhotoPipeExecutor()
    monkeypatch.setattr(adapter, "runner", lambda run: media)
    tick(session, "replacement-owner-worker", executors={media.name: adapter}, runner=media)
    assert session.get(Run, identity).status == "succeeded" and media.starts == 0
    session.commit()
    for account, count in ((owner, 1), (other_owner, 0)):
        with ScopedSession(bind=get_engine(), scope=DataScope(account), expire_on_commit=False) as private:
            assert len(list(private.scalars(select(Artifact).where(Artifact.run_id == identity)))) == count
