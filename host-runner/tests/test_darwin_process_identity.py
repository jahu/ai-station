"""Simulated Darwin ABI on normal CI; native self inspection only on a Mac."""

import ctypes
import errno
import os
import sys
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from ai_station_runner import darwin_process_identity as darwin

BOOT = "12345678-1234-4567-8234-123456789abc"


@pytest.fixture
def kernel(monkeypatch):
    state = {
        "calls": [],
        "boot": BOOT.upper().encode(),
        "boot_result": 0,
        "boot_size": None,
        "mutate": lambda value, count: None,
        "returned": 136,
        "errno": 0,
        "session": 37,
    }

    class Info:
        count = 0

        def __call__(self, pid, flavor, argument, buffer, size):
            assert (pid, flavor, argument, size) == (37, 3, 0, 136)
            self.count += 1
            state["calls"].append("process")
            value = ctypes.cast(buffer, ctypes.POINTER(darwin._BSDInfo)).contents
            value.pid = pid
            value.uid = os.geteuid()
            value.pgid = pid
            value.prefix[1] = 2
            value.command = b"private-prompt"
            value.name = b"private-executor-name"
            value.started_seconds = 1_700_000_000
            value.started_microseconds = 123456
            state["mutate"](value, self.count)
            ctypes.set_errno(state["errno"])
            return state["returned"]

    class Boot:
        def __call__(self, key, buffer, length, new, new_length):
            assert key == b"kern.bootsessionuuid" and new is None and new_length == 0
            assert len(buffer) == 64
            state["calls"].append("boot")
            buffer.value = state["boot"]
            ctypes.cast(length, ctypes.POINTER(ctypes.c_size_t)).contents.value = (
                state["boot_size"] if state["boot_size"] is not None else len(state["boot"]) + 1
            )
            ctypes.set_errno(state["errno"])
            return state["boot_result"]

    info, boot = Info(), Boot()

    def load(name, *, use_errno):
        assert use_errno is True
        if name == "/usr/lib/libproc.dylib":
            return SimpleNamespace(proc_pidinfo=info)
        assert name is None
        return SimpleNamespace(sysctlbyname=boot)

    monkeypatch.setattr(darwin.sys, "platform", "darwin")
    monkeypatch.setattr(darwin.ctypes, "CDLL", load)
    monkeypatch.setattr(darwin.os, "getsid", lambda pid: state["session"])
    return state


def test_public_abi_layout_and_private_identity_are_not_linux_journal_fields(kernel):
    assert ctypes.sizeof(darwin._BSDInfo) == 136
    assert darwin._BSDInfo.started_seconds.offset == 120
    assert darwin._BSDInfo.started_microseconds.offset == 128
    value = darwin.snapshot(37)
    assert asdict(value) == {
        "boot_id": BOOT,
        "pid": 37,
        "uid": os.geteuid(),
        "pgid": 37,
        "session": 37,
        "started_us": 1_700_000_000_123456,
        "state": 2,
        "format": "darwin-bsdinfo-us-v1",
    }
    assert kernel["calls"] == ["boot", "process", "process"]


@pytest.mark.parametrize("field", ["pid", "pgid", "started_seconds", "started_microseconds"])
def test_pid_reuse_or_group_change_during_session_lookup_is_not_adopted(kernel, field):
    def change(value, count):
        if count == 2:
            setattr(value, field, getattr(value, field) + 1)

    kernel["mutate"] = change
    with pytest.raises(OSError):
        darwin.snapshot(37)


def test_normal_process_state_changes_do_not_look_like_pid_reuse(kernel):
    kernel["mutate"] = lambda value, count: value.prefix.__setitem__(1, 3 if count == 2 else 2)
    assert darwin.snapshot(37).state == 3


def test_foreign_effective_user_is_rejected(kernel):
    kernel["mutate"] = lambda value, count: setattr(value, "uid", os.geteuid() + 1)
    with pytest.raises(PermissionError, match="another OS user"):
        darwin.snapshot(37)
    assert kernel["calls"] == ["boot", "process"]


@pytest.mark.parametrize("failure", ["library", "symbol"])
def test_missing_native_inspection_is_not_replaced_with_a_weaker_identity(kernel, monkeypatch, failure):
    def unavailable(*args, **kwargs):
        if failure == "library":
            raise OSError("system library unavailable")
        return SimpleNamespace()

    monkeypatch.setattr(darwin.ctypes, "CDLL", unavailable)
    with pytest.raises(OSError, match="inspection is unavailable"):
        darwin.snapshot(37)
    assert not kernel["calls"]


def test_disappearing_process_during_session_lookup_is_not_reported_owned(kernel, monkeypatch):
    def gone(pid):
        raise ProcessLookupError(errno.ESRCH, "process exited")

    monkeypatch.setattr(darwin.os, "getsid", gone)
    with pytest.raises(ProcessLookupError):
        darwin.snapshot(37)
    assert kernel["calls"] == ["boot", "process"]


@pytest.mark.parametrize("returned,error", [(0, errno.ESRCH), (0, errno.EPERM), (128, 0)])
def test_gone_denied_and_short_snapshots_are_errors_not_empty_success(kernel, returned, error):
    kernel.update(returned=returned, errno=error)
    with pytest.raises(OSError) as caught:
        darwin.snapshot(37)
    assert caught.value.errno == (error or errno.EIO)


@pytest.mark.parametrize(
    "field,value", [("pgid", 0), ("started_seconds", 0), ("started_microseconds", 1_000_000)]
)
def test_invalid_native_identity_does_not_become_an_owned_process(kernel, field, value):
    kernel["mutate"] = lambda record, count: setattr(record, field, value)
    with pytest.raises(OSError, match="invalid"):
        darwin.snapshot(37)


@pytest.mark.parametrize(
    "boot,size",
    [(b"", None), (b"not-a-boot-uuid", None), (b"0" * 36, None), (BOOT.encode(), 65), (BOOT.encode(), 36)],
)
def test_malformed_boot_identity_prevents_process_inspection(kernel, boot, size):
    kernel.update(boot=boot, boot_size=size)
    with pytest.raises(OSError, match="boot identity"):
        darwin.snapshot(37)
    assert kernel["calls"] == ["boot"]


def test_boot_query_failure_does_not_fall_back_to_wall_clock(kernel):
    kernel.update(boot_result=-1, errno=errno.EPERM)
    with pytest.raises(PermissionError):
        darwin.snapshot(37)
    assert kernel["calls"] == ["boot"]


@pytest.mark.parametrize("pid", [True, False, 0, -1, 2**31, "37"])
def test_invalid_pid_never_reaches_native_calls(kernel, pid):
    with pytest.raises(ValueError):
        darwin.snapshot(pid)
    assert not kernel["calls"]


def test_other_platform_cannot_load_darwin_system_libraries(monkeypatch):
    monkeypatch.setattr(darwin.sys, "platform", "linux")
    monkeypatch.setattr(darwin.ctypes, "CDLL", lambda *a, **k: pytest.fail("Unexpected Darwin library load"))
    with pytest.raises(OSError, match="native macOS"):
        darwin.snapshot(37)


@pytest.mark.skipif(sys.platform != "darwin", reason="Requires a real native Mac kernel")
def test_native_self_identity_matches_the_actual_os_process():
    first, second = darwin.snapshot(os.getpid()), darwin.snapshot(os.getpid())
    assert first.pid == os.getpid() and first.uid == os.geteuid()
    assert first.pgid == os.getpgid(0) and first.session == os.getsid(0)
    assert first.boot_id == second.boot_id and first.started_us == second.started_us
