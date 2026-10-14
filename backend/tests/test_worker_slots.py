import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from app.config import Settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import ResourceLock, Run, WorkerRow
from app.resources import release_run_locks, reserve_gpu
from app.runs import create_run, create_task, request_cancel, transition
from pydantic import ValidationError
from sqlalchemy import select


def enqueue(session, executor="fake"):
    task = create_task(session, title="slot test", prompt="", capability="test")
    run = create_run(
        session,
        task,
        run_type="test",
        capability="test",
        executor_type=executor,
        execution_target="container",
        requested_gpu="7" if executor == "slow" else "none",
    )
    session.commit()
    return run.id


def test_slow_run_does_not_block_short_work_or_share_gpu(session, monkeypatch):
    monkeypatch.setenv("AI_STATION_HEARTBEAT_SECONDS", "1")
    from app.config import clear_settings_cache
    from app.executors import FakeExecutor

    clear_settings_cache()
    started, finish = Event(), Event()

    class Slow:
        def execute(self, current, run):
            assert reserve_gpu(current, run, [7]) == "7"
            transition(current, run, "preparing", event_type="executor.preparing")
            transition(current, run, "running", event_type="executor.started")
            current.commit()
            started.set()
            assert finish.wait(10)
            current.refresh(run)
            assert run.status == "cancel_requested"
            transition(current, run, "canceled", event_type="run.canceled")
            release_run_locks(current, run.id)

    slow = enqueue(session, "slow")
    fast = enqueue(session)

    def execute(identity):
        with session_factory()() as current:
            return tick(current, identity, executors={"slow": Slow(), "fake": FakeExecutor()})

    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(execute, "worker/slot-1")
        try:
            assert started.wait(5)
            session.rollback()
            other_gpu = enqueue(session)
            competitor = session.get(Run, other_gpu)
            competitor.requested_gpu = "7"
            assert reserve_gpu(session, competitor, [7]) is None
            session.commit()
            assert pool.submit(execute, "worker/slot-2").result(timeout=5) == fast
            session.expire_all()
            assert session.get(Run, fast).status == "succeeded"
            assert session.get(Run, slow).status == "running"
            assert (
                len(list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None)))))
                == 1
            )
            session.commit()
            time.sleep(1.2)
            session.expire_all()
            held = session.get(Run, slow)
            assert held.worker_id == "worker/slot-1"
            assert held.lease_expires_at > utcnow()
            request_cancel(session, held)
            session.commit()
        finally:
            session.rollback()
            finish.set()
        assert future.result(timeout=5) == slow
    session.expire_all()
    assert session.get(Run, slow).status == "canceled"
    assert session.scalar(select(ResourceLock).where(ResourceLock.released_at.is_(None))) is None


def wait_until(check, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for worker lifecycle")


def children(pid):
    path = Path(f"/proc/{pid}/task/{pid}/children")
    return [int(value) for value in path.read_text().split()] if path.exists() else []


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


@pytest.mark.parametrize("slots,action", [(1, signal.SIGINT), (3, signal.SIGTERM), (3, "crash")])
def test_supervisor_owns_slots_and_stops_all_children(session, tmp_path, slots, action):
    run_id = enqueue(session)
    env = {**os.environ, "AI_STATION_WORKER_SLOTS": str(slots), "AI_STATION_WORKER_ID": "test-group"}
    # Isolated cwd prevents loading any operator .env in spawned processes.
    repository = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = os.pathsep.join(str(repository / value) for value in ("backend", "host-runner"))
    owned = []
    with (tmp_path / "worker.log").open("w+") as log:
        parent = subprocess.Popen(
            [sys.executable, "-m", "app.worker_main"],
            cwd=tmp_path,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:

            def ready():
                with session_factory()() as current:
                    workers = list(current.scalars(select(WorkerRow)))
                    return len(workers) == slots and current.get(Run, run_id).status == "succeeded"

            wait_until(ready)
            owned = children(parent.pid)
            assert len(owned) >= slots
            with session_factory()() as current:
                identities = {worker.id for worker in current.scalars(select(WorkerRow))}
            assert identities == (
                {"test-group"} if slots == 1 else {f"test-group/slot-{index + 1}" for index in range(slots)}
            )
            if action == "crash":
                slot = next(
                    pid
                    for pid in owned
                    if b"multiprocessing.spawn" in Path(f"/proc/{pid}/cmdline").read_bytes()
                )
                os.kill(slot, signal.SIGKILL)
            else:
                parent.send_signal(action)
            assert (parent.wait(timeout=10) != 0) == (action == "crash")
            wait_until(lambda: all(not alive(pid) for pid in owned))
        finally:
            if parent.poll() is None:
                parent.terminate()
                parent.wait(timeout=10)
            for pid in owned:
                if alive(pid):
                    os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize("slots", [0, 9])
def test_worker_slots_are_bounded(slots):
    with pytest.raises(ValidationError):
        Settings(worker_slots=slots)
