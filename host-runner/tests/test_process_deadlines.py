import json
import os
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from ai_station_runner import processes
from ai_station_runner.processes import ProcessManager


def launch(manager, tmp_path, *, deadline=None, program="import time; time.sleep(30)"):
    return manager.start(
        run_id=str(uuid4()),
        argv=[sys.executable, "-c", program],
        cwd=tmp_path,
        executor="deadline-test",
        deadline_at=deadline,
    )


def stopped(manager, run_id):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        result = manager.inspect(run_id)
        if not result["alive"] and not result["completion_pending"]:
            return result
        time.sleep(0.02)
    pytest.fail("Owned process group survived its budget")


def test_native_deadline_cancels_only_its_owned_group_and_cannot_be_extended(tmp_path):
    manager = ProcessManager(tmp_path, grace_seconds=0.03)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    record = launch(manager, tmp_path, deadline=time.time() + 0.4)
    try:
        replay = manager.start(
            run_id=record["run_id"],
            argv=[sys.executable, "-c", "raise AssertionError('replayed')"],
            cwd=tmp_path,
            executor="deadline-test",
            deadline_at=time.time() + 30,
        )
        assert replay["pid"] == record["pid"]
        assert replay["deadline_at"] == record["deadline_at"]
        result = stopped(manager, record["run_id"])
        assert result["status"] == "canceled" and result["deadline_exceeded_at"] >= record["deadline_at"]
        assert unrelated.poll() is None
    finally:
        manager.shutdown()
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_deadline_is_kept_when_a_forked_child_outlives_its_leader(tmp_path):
    manager = ProcessManager(tmp_path, grace_seconds=0.03)
    record = launch(
        manager,
        tmp_path,
        deadline=time.time() + 1.5,
        program="import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); print('forked', flush=True)",
    )
    try:
        result = stopped(manager, record["run_id"])
        assert "forked" in result["stdout"]
        assert result["status"] == "canceled" and result["deadline_exceeded_at"]
    finally:
        manager.shutdown()


def test_native_restart_restores_the_original_deadline_without_replaying(tmp_path, monkeypatch):
    original = ProcessManager(tmp_path, grace_seconds=0.03)
    # Emulate the old native service disappearing: no waiter or timer survives.
    monkeypatch.setattr(original, "_wait", lambda *args: None)
    record = launch(original, tmp_path, deadline=time.time() + 0.5)
    original._deadline_timers.pop(record["run_id"]).cancel()
    process = original._live[record["run_id"]]
    restored = ProcessManager(tmp_path, grace_seconds=0.03)
    try:
        result = stopped(restored, record["run_id"])
        assert result["pid"] == record["pid"] and result["deadline_at"] == record["deadline_at"]
        assert result["status"] == "canceled" and result["exit_code"] is None
    finally:
        restored.shutdown()
        process.wait(timeout=5)


def test_deadline_never_signals_a_reused_or_unverifiable_pid(tmp_path):
    manager = ProcessManager(tmp_path, grace_seconds=0.03)
    record = launch(manager, tmp_path, deadline=time.time() + 0.3)
    process = manager._live[record["run_id"]]
    try:
        with manager._lock:
            records = json.loads(manager.path.read_text())
            records[record["run_id"]]["start_ticks"] += 1
            manager._dump(records)
        time.sleep(0.5)
        assert process.poll() is None
        assert "deadline_exceeded_at" not in json.loads(manager.path.read_text())[record["run_id"]]
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


@pytest.mark.parametrize("deadline", [True, 0, -1, float("inf"), float("nan"), "later"])
def test_invalid_budgets_are_rejected_before_any_process_is_launched(tmp_path, deadline):
    manager = ProcessManager(tmp_path)
    with pytest.raises(ValueError, match="within the next hour"):
        launch(manager, tmp_path, deadline=deadline)
    assert json.loads(manager.path.read_text()) == {}


def test_processes_without_budgets_keep_their_original_lifecycle(tmp_path):
    manager = ProcessManager(tmp_path, grace_seconds=0.03)
    record = launch(manager, tmp_path)
    try:
        assert "deadline_at" not in record and not manager._deadline_timers
        assert manager.inspect(record["run_id"])["alive"]
    finally:
        manager.shutdown()


def test_verified_live_leader_is_not_lost_in_a_later_fork_exit_snapshot(monkeypatch):
    record = {"boot_id": "this-boot", "pid": 123, "process_group_id": 123, "start_ticks": 42}
    monkeypatch.setattr(processes, "_boot_id", lambda: "this-boot")
    monkeypatch.setattr(
        processes,
        "_identity",
        lambda pid: {"state": "R", "pgid": 123, "session": 123, "start_ticks": 42},
    )
    # A concurrent fork/leader exit can make a later directory snapshot miss
    # both members. The already verified live identity remains authoritative.
    monkeypatch.setattr(processes.Path, "iterdir", lambda self: iter(()))
    assert processes._group_alive(record)
