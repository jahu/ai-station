"""Candidate ownership contract; Linux process controls do not qualify native Mac."""

import ctypes
import errno
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import darwin_processes as darwin
from ai_station_runner import processes
from ai_station_runner.darwin_process_identity import DarwinIdentity

BOOT = "12345678-1234-4567-8234-123456789abc"


def identity(pid=37, **changes):
    return replace(DarwinIdentity(BOOT, pid, os.geteuid(), 37, 37, 1_700_000_000_123456, 2), **changes)


def record():
    return {"pid": 37, "process_group_id": 37, "boot_id": BOOT, "native_identity": asdict(identity())}


@pytest.fixture
def list_kernel(monkeypatch):
    state = {"ids": [37, 38], "returned": None, "errno": 0, "calls": []}

    def query(kind, group, values, size):
        assert (kind, group, size) == (2, 37, darwin.MAX_GROUP_MEMBERS * 4)
        state["calls"].append((kind, group))
        for index, pid in enumerate(state["ids"]):
            values[index] = pid
        ctypes.set_errno(state["errno"])
        return state["returned"] if state["returned"] is not None else len(state["ids"]) * 4

    def load(path, *, use_errno):
        assert path == "/usr/lib/libproc.dylib" and use_errno is True
        return SimpleNamespace(proc_listpids=query)

    monkeypatch.setattr(darwin, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(darwin.ctypes, "CDLL", load)
    return state


def test_native_group_query_uses_bytes_and_does_not_enumerate_unrelated_groups(list_kernel):
    assert darwin.group_members(37) == (37, 38)
    list_kernel["ids"] = []
    assert darwin.group_members(37) == ()


@pytest.mark.parametrize("returned,error", [(0, errno.EPERM), (0, errno.ESRCH), (-1, 0), (3, 0), (32768, 0)])
def test_denied_error_or_truncated_group_query_is_not_empty_success(list_kernel, returned, error):
    list_kernel.update(returned=returned, errno=error)
    with pytest.raises(OSError):
        darwin.group_members(37)


@pytest.mark.parametrize("pids", [[0], [-1], [37, 37]])
def test_invalid_or_duplicated_group_members_are_rejected(list_kernel, pids):
    list_kernel["ids"] = pids
    with pytest.raises(OSError, match="invalid process"):
        darwin.group_members(37)


@pytest.mark.parametrize("group", [0, -1, True, "37", 2**31])
def test_invalid_group_never_queries_the_native_library(list_kernel, group):
    with pytest.raises(ValueError):
        darwin.group_members(group)
    assert not list_kernel["calls"]


def test_other_os_cannot_load_native_group_library(monkeypatch):
    monkeypatch.setattr(darwin, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(darwin.ctypes, "CDLL", lambda *a, **k: pytest.fail("Unexpected native library"))
    with pytest.raises(OSError, match="native macOS"):
        darwin.group_members(37)


def test_exact_live_leader_does_not_depend_on_a_second_group_enumeration(monkeypatch):
    monkeypatch.setattr(darwin.kernel, "snapshot", lambda _: identity())
    monkeypatch.setattr(darwin, "group_members", lambda _: pytest.fail("Leader already proves owned work"))
    assert darwin.group_alive(record())


@pytest.mark.parametrize(
    "field,value", [("format", "linux"), ("uid", -1), ("pgid", 0), ("session", 0), ("started_us", True)]
)
def test_incomplete_or_foreign_journal_cannot_authorize_group_adoption(monkeypatch, field, value):
    saved = record()
    saved["native_identity"][field] = value
    monkeypatch.setattr(darwin.kernel, "snapshot", lambda _: pytest.fail("Invalid journal reached kernel"))
    with pytest.raises(ValueError, match="complete owned"):
        darwin.group_alive(saved)


def test_legacy_linux_journal_cannot_be_reinterpreted_as_native_microseconds():
    with pytest.raises(ValueError):
        darwin.group_alive({"pid": 37, "start_ticks": 123, "process_group_id": 37, "boot_id": BOOT})


def test_reused_leader_pid_never_authorizes_its_new_group(monkeypatch):
    monkeypatch.setattr(
        darwin.kernel, "snapshot", lambda pid: identity(started_us=17) if pid == 37 else identity()
    )
    monkeypatch.setattr(darwin, "group_members", lambda _: pytest.fail("Reused leader was adopted"))
    assert not darwin.group_alive(record())


def test_another_boot_is_not_adopted(monkeypatch):
    monkeypatch.setattr(darwin.kernel, "snapshot", lambda _: identity(boot_id="other-boot"))
    assert not darwin.group_alive(record())


@pytest.mark.parametrize("leader", [None, identity(state=5)])
def test_surviving_descendant_after_leader_exit_requires_the_original_session(monkeypatch, leader):
    def observe(pid):
        if pid == 37:
            if leader is None:
                raise ProcessLookupError(errno.ESRCH, "gone")
            return leader
        return identity(pid=pid, started_us=1_700_000_000_123457)

    monkeypatch.setattr(darwin.kernel, "snapshot", observe)
    monkeypatch.setattr(darwin, "group_members", lambda _: (38,))
    assert darwin.group_alive(record())
    original = observe
    monkeypatch.setattr(
        darwin.kernel,
        "snapshot",
        lambda pid: replace(original(pid), session=99) if pid == 38 else original(pid),
    )
    assert not darwin.group_alive(record())


def test_inspection_denial_is_not_group_gone(monkeypatch):
    def denied(pid):
        if pid == os.getpid():
            return identity(pid=pid)
        raise PermissionError(errno.EPERM, "cannot inspect")

    monkeypatch.setattr(darwin.kernel, "snapshot", denied)
    with pytest.raises(PermissionError):
        darwin.group_alive(record())


@pytest.mark.parametrize(
    "field,value",
    [
        ("pid", 38),
        ("pgid", 0),
        ("session", 0),
        ("uid", -1),
        ("format", "unknown"),
        ("state", 5),
        ("started_us", 0),
        ("boot_id", "other"),
    ],
)
def test_capture_must_confirm_the_exact_new_session_before_gate_release(monkeypatch, field, value):
    monkeypatch.setattr(darwin.kernel, "snapshot", lambda _: identity(**{field: value}))
    with pytest.raises(OSError, match="expected owned session"):
        darwin.DarwinProcessManager._capture_identity(37, BOOT)


def install_linux_control(monkeypatch):
    def observe(pid):
        value = processes._identity(pid)
        if value is None:
            raise ProcessLookupError(errno.ESRCH, "gone")
        return DarwinIdentity(
            BOOT,
            pid,
            os.geteuid(),
            value["pgid"],
            value["session"],
            value["start_ticks"] * 10000,
            5 if value["state"] in {"Z", "X"} else 2,
        )

    def members(pgid):
        result = []
        for path in Path("/proc").iterdir():
            if path.name.isdigit():
                value = processes._identity(int(path.name))
                if value and value["pgid"] == pgid:
                    result.append(int(path.name))
        return result

    monkeypatch.setattr(darwin.kernel, "snapshot", observe)
    monkeypatch.setattr(darwin, "group_members", members)


@pytest.fixture
def candidate_kernel(monkeypatch):
    if sys.platform == "darwin":
        if os.getenv("AI_STATION_REAL_MAC_PROCESS_TESTS") != "1":
            pytest.skip("Explicit opt-in is required for actual Mac process qualification")
        # Same contract tests, with actual native identity/enumeration below.
    elif sys.platform == "linux":
        install_linux_control(monkeypatch)
    else:
        pytest.skip("No native/control process fixture for this platform")
    managers = []
    original = darwin.DarwinProcessManager.__init__

    def track(manager, *args, **kwargs):
        original(manager, *args, **kwargs)
        managers.append(manager)

    monkeypatch.setattr(darwin.DarwinProcessManager, "__init__", track)
    try:
        yield
    finally:
        # Wait for only these fixtures' normal reapers before restoring kernel
        # mocks; no lingering thread should inspect the next test's platform.
        for manager in managers:
            manager.shutdown()
            deadline = time.monotonic() + 5
            while manager._live and time.monotonic() < deadline:
                time.sleep(0.01)
            with manager._lock:
                assert not manager._live


def await_done(manager, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = manager.inspect(run_id)
        if not value["alive"] and not value["completion_pending"]:
            return value
        time.sleep(0.01)
    raise AssertionError("Owned process did not complete")


@pytest.mark.parametrize("capture", [True, False])
def test_candidate_gate_execs_only_after_durable_identity_and_keeps_original_pid(
    tmp_path, monkeypatch, candidate_kernel, capture
):
    manager = darwin.DarwinProcessManager(tmp_path)
    marker = tmp_path / "result"
    original = manager._dump
    published = []

    def persist(records):
        if records and not published:
            assert not marker.exists()
            value = next(iter(records.values()))
            assert "start_ticks" not in value and value["native_identity"]["pid"] == value["pid"]
            time.sleep(0.1)  # Workload still cannot run while publication is pending.
            assert not marker.exists()
            published.append(value["pid"])
        original(records)

    monkeypatch.setattr(manager, "_dump", persist)
    run_id = str(uuid4())
    manager.start(
        run_id=run_id,
        argv=[
            sys.executable,
            "-c",
            "import os,pathlib;pathlib.Path('result').write_text(str(os.getpid()));print('GATED-OUTPUT')",
        ],
        cwd=tmp_path,
        executor="test",
        capture_output=capture,
    )
    monkeypatch.setattr(manager, "_dump", original)
    result = await_done(manager, run_id)
    assert result["status"] == "exited" and result["exit_code"] == 0
    assert int(marker.read_text()) == published[0] == result["pid"]
    assert ("GATED-OUTPUT" in result["stdout"]) is capture


def test_candidate_failed_publication_never_executes_workload(tmp_path, monkeypatch, candidate_kernel):
    manager = darwin.DarwinProcessManager(tmp_path)
    child = []

    def fail(records):
        child.append(next(iter(records.values()))["pid"])
        raise OSError("Publication unavailable")

    monkeypatch.setattr(manager, "_dump", fail)
    with pytest.raises(OSError, match="Publication"):
        manager.start(
            run_id=str(uuid4()),
            argv=[sys.executable, "-c", "open('should-not-exist','w').close()"],
            cwd=tmp_path,
            executor="test",
        )
    assert not (tmp_path / "should-not-exist").exists()
    assert json.loads(manager.path.read_text()) == {}
    assert darwin._snapshot(child[0]) is None


def test_native_child_socket_is_private_even_when_parent_umask_is_public(tmp_path, candidate_kernel):
    manager = darwin.DarwinProcessManager(tmp_path, grace_seconds=0.05)
    run_id = str(uuid4())
    previous = os.umask(0o022)
    try:
        manager.start(
            run_id=run_id,
            executor="test",
            cwd=tmp_path,
            argv=[
                sys.executable,
                "-c",
                "import socket,pathlib,time;s=socket.socket(socket.AF_UNIX);s.bind('private.sock');pathlib.Path('ready').touch();time.sleep(30)",
            ],
        )
        deadline = time.monotonic() + 3
        while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "ready").exists()
        assert (tmp_path / "private.sock").stat().st_mode & 0o077 == 0
        assert os.umask(0o022) == 0o022  # Only the child policy changes.
    finally:
        os.umask(previous)
        manager.shutdown()


def test_native_launch_barrier_does_not_write_interpreter_cache(tmp_path, monkeypatch, candidate_kernel):
    cache = tmp_path / "bytecode"
    wrapper = tmp_path / "isolated-python"
    wrapper.write_text(
        "#!/bin/sh\nexec "
        + shlex.quote(sys.executable)
        + " -X "
        + shlex.quote("pycache_prefix=" + str(cache))
        + ' "$@"\n'
    )
    wrapper.chmod(0o700)
    monkeypatch.setattr(darwin, "sys", SimpleNamespace(executable=str(wrapper), platform=sys.platform))
    manager = darwin.DarwinProcessManager(tmp_path)
    run_id = str(uuid4())
    try:
        manager.start(run_id=run_id, executor="test", cwd=tmp_path, argv=["/usr/bin/true"])
        result = await_done(manager, run_id)
        assert result["exit_code"] == 0
        assert not cache.exists()  # New bytecode must not mutate the shipped interpreter.
    finally:
        manager.shutdown()


def test_candidate_failed_identity_capture_never_executes_unrecorded_work(
    tmp_path, monkeypatch, candidate_kernel
):
    manager = darwin.DarwinProcessManager(tmp_path)
    child = []

    def fail(pid, boot):
        child.append(pid)
        raise PermissionError(errno.EPERM, "Inspection denied")

    monkeypatch.setattr(manager, "_capture_identity", fail)
    with pytest.raises(PermissionError):
        manager.start(
            run_id=str(uuid4()),
            argv=[sys.executable, "-c", "open('should-not-exist','w').close()"],
            cwd=tmp_path,
            executor="test",
        )
    assert not (tmp_path / "should-not-exist").exists()
    assert json.loads(manager.path.read_text()) == {}
    assert darwin._snapshot(child[0]) is None


@pytest.mark.skipif(os.name != "posix", reason="Native exec barrier requires POSIX inherited pipes")
@pytest.mark.parametrize("acknowledgement", [b"", b"bad"])
def test_actual_gate_eof_or_wrong_acknowledgement_never_executes(tmp_path, acknowledgement):
    from ai_station_runner import process_gate

    read, write = os.pipe()
    try:
        child = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                process_gate.__file__,
                str(read),
                sys.executable,
                "-c",
                "open('should-not-exist','w').close()",
            ],
            cwd=tmp_path,
            pass_fds=(read,),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.close(read)
        read = None
        if acknowledgement:
            os.write(write, acknowledgement)
        os.close(write)
        write = None
        assert child.wait(timeout=5) != 0
        assert not (tmp_path / "should-not-exist").exists()
    finally:
        if read is not None:
            os.close(read)
        if write is not None:
            os.close(write)
        if "child" in locals() and child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


def test_candidate_restart_and_stop_only_the_owned_group(tmp_path, candidate_kernel):
    from test_runner_platform import exited_owner

    manager = None
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    run_id = str(uuid4())
    try:
        # Recovery begins only after the real owner exits, not concurrently
        # with its reaper writing the same journal under a different lock.
        first = exited_owner(tmp_path, run_id, native_mode=True)
        manager = darwin.DarwinProcessManager(tmp_path, grace_seconds=0.05)
        again = manager.start(
            run_id=run_id,
            argv=[sys.executable, "-c", "raise Exception()"],
            cwd=tmp_path,
            executor="platform-fixture",
        )
        assert first["pid"] == again["pid"]
        assert manager.cancel(run_id)["status"] == "canceled"
        assert unrelated.poll() is None
    finally:
        if manager is None:
            manager = darwin.DarwinProcessManager(tmp_path, grace_seconds=0.05)
        manager.shutdown()
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_candidate_reused_pid_in_journal_cannot_authorize_a_signal(tmp_path, monkeypatch, candidate_kernel):
    from test_runner_platform import exited_owner

    run_id = str(uuid4())
    original = exited_owner(tmp_path, run_id, native_mode=True)
    manager = darwin.DarwinProcessManager(tmp_path, grace_seconds=0.05)
    records = manager._load()
    records[run_id]["native_identity"]["started_us"] += 1
    manager._dump(records)
    calls = []
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "killpg", lambda *args: calls.append(args))
            assert manager.cancel(run_id)["status"] == "interrupted"
            assert not calls and manager._process_alive(original)
    finally:
        manager._dump({run_id: original})
        manager.shutdown()


def test_candidate_deadline_retains_existing_engine_and_private_journal(tmp_path, candidate_kernel):
    manager = darwin.DarwinProcessManager(tmp_path, grace_seconds=0.05)
    run_id = str(uuid4())
    try:
        manager.start(
            run_id=run_id,
            argv=[sys.executable, "-c", "import time;time.sleep(30)"],
            cwd=tmp_path,
            executor="test",
            deadline_at=time.time() + 0.25,
        )
        result = await_done(manager, run_id)
        assert result["status"] == "canceled" and result["deadline_exceeded_at"]
        assert manager.path.stat().st_mode & 0o777 == 0o600
    finally:
        manager.shutdown()


def test_candidate_cancel_descendants_after_the_gated_leader_exits(tmp_path, candidate_kernel):
    manager = darwin.DarwinProcessManager(tmp_path, grace_seconds=0.05)
    run_id = str(uuid4())
    child_script = "import signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path('child-ready').touch();time.sleep(30)"
    script = "import subprocess,sys;subprocess.Popen([sys.executable,'-c'," + repr(child_script) + "])"
    try:
        manager.start(run_id=run_id, argv=[sys.executable, "-c", script], cwd=tmp_path, executor="test")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (not (tmp_path / "child-ready").exists() or manager._live):
            time.sleep(0.01)
        assert (tmp_path / "child-ready").exists() and not manager._live
        assert manager.inspect(run_id)["alive"]
        assert manager.cancel(run_id)["status"] == "canceled"
        assert not manager.inspect(run_id)["alive"]
    finally:
        manager.shutdown()


@pytest.mark.skipif(
    sys.platform != "darwin" or os.getenv("AI_STATION_REAL_MAC_PROCESS_TESTS") != "1",
    reason="Opt-in actual Mac kernel launch/Stop/recovery; Linux controls are not Mac evidence",
)
def test_actual_native_mac_launch_recovery_and_stop(tmp_path):
    run_id = str(uuid4())
    # Production main holds one runner.lock. A second live manager in this
    # process creates an impossible two-writer race with the first reaper.
    # Recover only after the original owner has actually exited and been reaped.
    helper = """
import json,os,sys
from pathlib import Path
from ai_station_runner.darwin_processes import DarwinProcessManager
root=Path(sys.argv[1]);manager=DarwinProcessManager(root,grace_seconds=0.1)
result=manager.start(run_id=sys.argv[2],argv=[sys.executable,'-c','import time;time.sleep(30)'],cwd=root,executor='test')
print(json.dumps(result),flush=True)
os._exit(0)
"""
    recovered = None
    try:
        owner = subprocess.run(
            [sys.executable, "-B", "-c", helper, str(tmp_path), run_id],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        result = json.loads(owner.stdout)
        assert result["pid"] == result["native_identity"]["pid"]
        assert result["native_identity"]["format"] == darwin.FORMAT
        recovered = darwin.DarwinProcessManager(tmp_path, grace_seconds=0.1)
        assert recovered.cancel(run_id)["status"] == "canceled"
    finally:
        if recovered is None:
            recovered = darwin.DarwinProcessManager(tmp_path, grace_seconds=0.1)
        recovered.shutdown()
