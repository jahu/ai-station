import json
import os
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from ai_station_runner.processes import ProcessManager, ProcessNotOwned


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
