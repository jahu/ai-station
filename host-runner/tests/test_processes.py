import json
import os
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from ai_station_runner import processes
from ai_station_runner.processes import ProcessManager, ProcessNotOwned


@pytest.mark.parametrize("capture", [True, False])
def test_process_output_policy_is_durable_and_cannot_change_on_retry(tmp_path, capture):
    manager = ProcessManager(tmp_path, grace_seconds=0.05)
    run_id = str(uuid4())
    kwargs = {
        "run_id": run_id,
        "cwd": tmp_path,
        "executor": "test",
        "argv": [
            sys.executable,
            "-c",
            "import sys;print('PRIVATE-OUTPUT');print('PRIVATE-ERROR',file=sys.stderr)",
        ],
        "capture_output": capture,
    }
    try:
        manager.start(**kwargs)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = manager.inspect(run_id)
            if not result["alive"] and not result["completion_pending"]:
                break
            time.sleep(0.01)
        assert result["exit_code"] == 0
        assert ("PRIVATE-OUTPUT" in result["stdout"]) is capture
        assert ("PRIVATE-ERROR" in result["stderr_tail"]) is capture
        if not capture:
            assert result["stdout"] == result["stderr_tail"] == ""
            assert result["logs_suppressed"] is True
        replacement = ProcessManager(tmp_path)
        assert replacement.start(**kwargs)["pid"] == result["pid"]
        with pytest.raises(ValueError, match="output policy"):
            replacement.start(**(kwargs | {"capture_output": not capture}))
    finally:
        manager.shutdown()


def test_nonboolean_output_policy_is_rejected_before_launch(tmp_path):
    manager = ProcessManager(tmp_path)
    with pytest.raises(ValueError, match="output policy"):
        manager.start(run_id=str(uuid4()), argv=["true"], cwd=tmp_path, executor="test", capture_output=0)
    assert manager._load() == {} and not manager._live


@pytest.mark.parametrize("failure", ["unreadable", "empty", "unsupported"])
def test_boot_identity_failure_cannot_launch_an_unrecorded_child(tmp_path, monkeypatch, failure):
    manager = ProcessManager(tmp_path)
    launched = []

    def forbidden(*args, **kwargs):
        launched.append(args)
        raise AssertionError("Process launch happened before boot identity preflight")

    monkeypatch.setattr(processes.subprocess, "Popen", forbidden)
    if failure == "unsupported":
        monkeypatch.setattr(processes.sys, "platform", "darwin")
        expected = RuntimeError
    elif failure == "empty":
        monkeypatch.setattr(processes, "_boot_id", lambda: "")
        expected = RuntimeError
    else:

        def unreadable():
            raise OSError("Boot identity cannot be inspected")

        monkeypatch.setattr(processes, "_boot_id", unreadable)
        expected = OSError
    with pytest.raises(expected):
        manager.start(run_id=str(uuid4()), argv=[sys.executable, "-c", "pass"], cwd=tmp_path, executor="test")
    assert not launched and not manager._live and not manager._deadline_timers
    assert json.loads(manager.path.read_text()) == {}
    assert not (tmp_path / "runs").exists()


def test_idempotent_launch_and_cancel_only_owned_group(tmp_path):
    manager = ProcessManager(tmp_path, grace_seconds=0.05)
    run_id = str(uuid4())
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        record = manager.start(
            run_id=run_id,
            argv=[sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            executor="test",
        )
        again = manager.start(
            run_id=run_id, argv=[sys.executable, "-c", "raise Exception()"], cwd=tmp_path, executor="test"
        )
        assert record["pid"] == again["pid"]
        assert manager.cancel(run_id)["status"] == "canceled"
        assert unrelated.poll() is None
        with pytest.raises(ProcessNotOwned):
            manager.cancel(str(uuid4()))
    finally:
        manager.cancel(run_id)
        unrelated.terminate()
        unrelated.wait()


def test_reused_pid_is_not_signaled(tmp_path, monkeypatch):
    manager = ProcessManager(tmp_path)
    run_id = str(uuid4())
    record = manager.start(
        run_id=run_id,
        argv=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        executor="test",
    )
    try:
        records = json.loads(manager.path.read_text())
        records[run_id]["start_ticks"] += 1
        manager.path.write_text(json.dumps(records))
        called = []
        with monkeypatch.context() as context:
            context.setattr(os, "killpg", lambda *args: called.append(args))
            restarted = ProcessManager(tmp_path)
            assert restarted.cancel(run_id)["status"] == "interrupted"
        assert not called
    finally:
        os.killpg(record["pid"], signal.SIGKILL)
        deadline = time.monotonic() + 2
        while manager._live and time.monotonic() < deadline:
            time.sleep(0.01)


def test_cancel_kills_descendants_after_leader_exits(tmp_path):
    manager = ProcessManager(tmp_path, grace_seconds=0.05)
    run_id = str(uuid4())
    script = (
        "import subprocess, sys; "
        'subprocess.Popen([sys.executable, "-c", "import signal,time; '
        'signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"])'
    )
    manager.start(run_id=run_id, argv=[sys.executable, "-c", script], cwd=tmp_path, executor="test")
    deadline = time.monotonic() + 2
    while manager._live and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert manager.inspect(run_id)["alive"]
        assert manager.cancel(run_id)["status"] == "canceled"
        assert not manager.inspect(run_id)["alive"]
    finally:
        manager.cancel(run_id)


def test_run_id_cannot_escape_storage(tmp_path):
    manager = ProcessManager(tmp_path)
    with pytest.raises(ValueError):
        manager.start(run_id="../escape", argv=["true"], cwd=tmp_path, executor="test")


def test_shutdown_stops_owned_work_without_stopping_unrelated_process(tmp_path):
    manager = ProcessManager(tmp_path, grace_seconds=0.05)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    run_ids = [str(uuid4()), str(uuid4())]
    try:
        for run_id in run_ids:
            manager.start(
                run_id=run_id,
                argv=[sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=tmp_path,
                executor="test",
            )
        manager.shutdown()
        assert all(not manager.inspect(run_id)["alive"] for run_id in run_ids)
        assert unrelated.poll() is None
    finally:
        manager.shutdown()
        unrelated.terminate()
        unrelated.wait()


def test_completion_polling_never_reports_a_successful_child_interrupted(tmp_path, monkeypatch):
    # Simulate the documented Popen race deterministically: a blocking waiter
    # owns waitpid while poll must return None. The manager must serialize its
    # reaping with inspection instead of starting that competing waiter.
    from threading import Event

    waiter_entered = Event()
    release_waiter = Event()
    real_wait = subprocess.Popen.wait

    def held_wait(proc, *args, **kwargs):
        with proc._waitpid_lock:
            waiter_entered.set()
            release_waiter.wait(2)
        return real_wait(proc, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "wait", held_wait)
    manager = ProcessManager(tmp_path)
    run_id = str(uuid4())
    manager.start(run_id=run_id, argv=[sys.executable, "-c", "pass"], cwd=tmp_path, executor="test")
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            record = manager.inspect(run_id)
            if not record["alive"]:
                assert record["status"] == "exited"
                assert record["exit_code"] == 0
                break
            time.sleep(0.01)
        else:
            raise AssertionError("Child never completed")
    finally:
        release_waiter.set()
        manager.shutdown()


def test_unreaped_child_keeps_completion_pending(tmp_path, monkeypatch):
    manager = ProcessManager(tmp_path)
    run_id = str(uuid4())
    manager.start(
        run_id=run_id,
        argv=[sys.executable, "-c", "import time; time.sleep(.3)"],
        cwd=tmp_path,
        executor="test",
    )
    # Native thread-group teardown can make procfs look finished before waitpid
    # exposes the exit code. Preserve that distinction instead of inventing loss.
    monkeypatch.setattr("ai_station_runner.processes._group_alive", lambda record: False)
    record = manager.inspect(run_id)
    assert not record["alive"] and record["completion_pending"]
    assert record["status"] == "running" and record["exit_code"] is None
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = manager.inspect(run_id)
        if not record["completion_pending"]:
            assert record["status"] == "exited" and record["exit_code"] == 0
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Exit status was never collected")
