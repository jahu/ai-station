"""Kernel ABI/policy tests; actual Mac observations remain separately opted in."""

import ctypes
import errno
import os
import sys
import time
from types import SimpleNamespace

import pytest
from ai_station_runner import darwin_telemetry as darwin
from ai_station_runner import telemetry


def test_native_loader_binds_fixed_system_symbols_without_commands_or_writes(monkeypatch):
    calls = []

    class Natural(ctypes.c_uint32):
        @classmethod
        def in_dll(cls, library, name):
            assert library is system and name == "mach_task_self_"
            return cls(42)

    system = SimpleNamespace(
        **{
            name: lambda *args: 0
            for name in (
                "mach_host_self",
                "mach_port_deallocate",
                "host_statistics",
                "host_statistics64",
                "host_page_size",
                "sysctlbyname",
            )
        }
    )

    def load(path, *, use_errno):
        calls.append(path)
        assert path == "/usr/lib/libSystem.B.dylib" and use_errno is True
        return system

    monkeypatch.setattr(darwin, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(darwin.ctypes, "CDLL", load)
    monkeypatch.setattr(darwin.ctypes, "c_uint32", Natural)
    native = darwin._Native()
    assert native.task == 42 and len(calls) == 1
    assert system.mach_host_self.restype is Natural
    assert system.host_statistics64.argtypes == [
        Natural,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.POINTER(Natural),
    ]
    assert system.sysctlbyname.argtypes[-1] is ctypes.c_size_t


@pytest.fixture
def kernel():
    native = darwin._Native.__new__(darwin._Native)
    state = {"calls": [], "release": 0, "stats": 0, "count": None, "page": 16384, "size": None, "error": 0}
    native.task = 42
    native.host = lambda: 37

    def release(task, port):
        state["calls"].append(("release", task, port))
        return state["release"]

    def statistics(port, flavor, output, count):
        state["calls"].append(("stats", port, flavor))
        number = ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32)).contents
        if flavor == 4:
            assert number.value == 40
            value = ctypes.cast(output, ctypes.POINTER(darwin._VM)).contents
            value.free_pages = 65536
            value.speculative_pages = 12000  # A subset of free, not additional RAM.
            value.purgeable_pages = 14000
            value.compressed_pages = 16000
            value.resident_counts[:] = (18000, 20000, 22000)
        else:
            assert flavor == 3 and number.value == 4
            output[:] = (100, 50, 250, 0)
        if state["count"] is not None:
            number.value = state["count"]
        return state["stats"]

    def page_size(port, output):
        assert port == 37
        ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32)).contents.value = state["page"]
        return 0

    def sysctl(key, output, size, new, new_size):
        assert new is None and new_size == 0
        state["calls"].append(("sysctl", key))
        length = ctypes.cast(size, ctypes.POINTER(ctypes.c_size_t)).contents
        if key == b"hw.memsize":
            assert length.value == 8
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint64)).contents.value = 16 * 1024**3
        else:
            assert key == b"vm.swapusage" and length.value == 32
            value = ctypes.cast(output, ctypes.POINTER(darwin._Swap)).contents
            value.total, value.used, value.available = 2048 * 1024**2, 256 * 1024**2, 1792 * 1024**2
            value.page_size, value.encrypted = 4096, 1
        if state["size"] is not None:
            length.value = state["size"]
        ctypes.set_errno(errno.EPERM if state["error"] else 0)
        return state["error"]

    native.release, native.statistics, native.statistics64 = release, statistics, statistics
    native.page_size, native.sysctl = page_size, sysctl
    return native, state


def test_public_layout_offsets_and_actual_page_size_no_double_counting(kernel):
    native, state = kernel
    assert ctypes.sizeof(darwin._VM) == 160
    assert darwin._VM.purgeable_pages.offset == 88
    assert darwin._VM.compressed_pages.offset == 128
    assert darwin._VM.swapped_pages.offset == 152
    assert ctypes.sizeof(darwin._Swap) == 32
    assert native.physical_memory() == 16 * 1024**3
    assert native.free_memory() == 1024**3
    assert native.swap() == (2048 * 1024**2, 256 * 1024**2)
    assert native.cpu_ticks() == (100, 50, 250, 0)
    assert state["calls"].count(("release", 42, 37)) == 2
    state["page"] = 4096
    assert native.free_memory() == 256 * 1024**2


@pytest.mark.parametrize("count", [38, 40])
def test_complete_public_vm_revisions_are_accepted(kernel, count):
    native, state = kernel
    state["count"] = count
    assert native.free_memory() > 0


@pytest.mark.parametrize("count", [0, 4, 37, 39, 41])
def test_short_unknown_or_torn_vm_revision_does_not_publish_free_ram(kernel, count):
    native, state = kernel
    state["count"] = count
    with pytest.raises(OSError, match="Incomplete native VM"):
        native.free_memory()
    assert state["calls"][-1] == ("release", 42, 37)


@pytest.mark.parametrize("page", [0, 1024, 5000, 131072])
def test_invalid_page_size_is_not_assumed_to_be_four_kib(kernel, page):
    native, state = kernel
    state["page"] = page
    with pytest.raises(OSError, match="page size"):
        native.free_memory()
    assert state["calls"] == [("release", 42, 37)]


@pytest.mark.parametrize("method", ["free_memory", "cpu_ticks"])
def test_failed_statistics_release_only_the_observation_port(kernel, method):
    native, state = kernel
    state["stats"] = 5
    with pytest.raises(OSError, match="statistics"):
        getattr(native, method)()
    assert state["calls"][-1] == ("release", 42, 37)


def test_host_port_failures_are_explicit(kernel):
    native, state = kernel
    state["release"] = 5
    with pytest.raises(OSError, match="released"):
        native.cpu_ticks()
    state["calls"].clear()
    native.host = lambda: 0
    with pytest.raises(OSError, match="host observation"):
        native.cpu_ticks()
    assert not state["calls"]


@pytest.mark.parametrize("method", ["physical_memory", "swap"])
@pytest.mark.parametrize("failure", ["short", "denied"])
def test_sysctl_never_returns_zeros_as_success_after_failed_or_short_read(kernel, method, failure):
    native, state = kernel
    state["size" if failure == "short" else "error"] = 1
    with pytest.raises(OSError):
        getattr(native, method)()
    assert len(state["calls"]) == 1 and state["calls"][0][0] == "sysctl"


@pytest.mark.parametrize("field,value", [("total", 1), ("available", 0), ("used", 2**63), ("encrypted", 2)])
def test_inconsistent_swap_data_stays_unavailable(kernel, field, value):
    native, _ = kernel
    original = native.sysctl

    def inconsistent(key, output, *args):
        code = original(key, output, *args)
        setattr(ctypes.cast(output, ctypes.POINTER(darwin._Swap)).contents, field, value)
        return code

    native.sysctl = inconsistent
    with pytest.raises(OSError, match="Invalid native swap"):
        native.swap()


def test_memory_uses_existing_keys_and_keeps_unknown_values_null(kernel, monkeypatch):
    native, state = kernel
    monkeypatch.setattr(darwin, "_Native", lambda: native)
    result = darwin.memory()
    assert result == {
        "total_mib": 16384.0,
        "used_mib": 15360.0,
        "available_mib": 1024.0,
        "swap_total_mib": 2048.0,
        "swap_used_mib": 256.0,
        "available_basis": "darwin_free_pages_only",
        "status": "available",
    }
    state["stats"] = 5
    result = darwin.memory()
    assert result["status"] == "partial" and result["total_mib"] == 16384.0
    assert result["used_mib"] is None and result["available_mib"] is None
    assert result["swap_used_mib"] == 256.0


def test_impossible_free_ram_is_not_an_admission_budget(kernel, monkeypatch):
    native, state = kernel
    monkeypatch.setattr(darwin, "_Native", lambda: native)
    state["page"] = 65536
    native.physical_memory = lambda: 1024**3
    result = darwin.memory()
    assert result["total_mib"] == 1024.0 and result["available_mib"] is None


def test_cpu_interval_wrap_failure_reset_and_unknown_temperature(monkeypatch):
    samples = iter([(100, 50, 250, 0), (150, 70, 280, 0), OSError(), (0, 0, 0, 0), (0, 0, 0, 0)])

    class Native:
        def cpu_ticks(self):
            value = next(samples)
            if isinstance(value, OSError):
                raise value
            return value

    monkeypatch.setattr(darwin, "_Native", Native)
    monkeypatch.setattr(darwin, "_previous_cpu", None)
    assert darwin.cpu() == {"utilization": None, "temperature_c": None}
    assert darwin.cpu() == {"utilization": 70.0, "temperature_c": None}
    assert darwin.cpu()["utilization"] is None
    assert darwin.cpu()["utilization"] is None  # No stale interval through failure.
    assert darwin.cpu()["utilization"] is None  # No ticks, not 0% utilization.


def test_cpu_uses_unsigned_wrap_without_reporting_reset_as_a_spike(monkeypatch):
    monkeypatch.setattr(darwin, "_previous_cpu", (2**32 - 20, 0, 100, 0))

    class Native:
        def cpu_ticks(self):
            return (10, 0, 170, 0)

    monkeypatch.setattr(darwin, "_Native", Native)
    assert darwin.cpu()["utilization"] == 30.0
    monkeypatch.setattr(darwin, "_previous_cpu", (100, 100, 200, 100))
    assert darwin.cpu()["utilization"] is None


def test_other_platform_never_loads_a_darwin_library_and_reports_unknown(monkeypatch):
    monkeypatch.setattr(darwin, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(darwin.ctypes, "CDLL", lambda *a, **k: pytest.fail("Unexpected library load"))
    monkeypatch.setattr(darwin, "_previous_cpu", None)
    with pytest.raises(OSError, match="requires macOS"):
        darwin._Native()
    assert darwin.cpu()["utilization"] is None
    assert darwin.memory()["status"] == "unavailable"
    assert darwin.memory()["available_mib"] is None


def test_darwin_collect_uses_native_observations_and_never_invents_nvidia_vram(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(darwin, "cpu", lambda: {"utilization": 12.5, "temperature_c": None})
    monkeypatch.setattr(darwin, "memory", lambda: {"available_mib": 123, "status": "partial"})
    monkeypatch.setattr(telemetry.nvidia, "executable", lambda: pytest.fail("Unexpected NVIDIA query"))
    monkeypatch.setattr(telemetry, "physical", lambda _: None)
    result = telemetry.collect(tmp_path)
    assert result["gpus"] == []
    assert result["cpu"]["utilization"] == 12.5
    assert result["memory"] == {"available_mib": 123, "status": "partial"}
    assert result["disk"]["free_bytes"] > 0 and len(result["load"]) == 3


@pytest.mark.skipif(
    sys.platform != "darwin" or os.getenv("AI_STATION_REAL_MAC_TELEMETRY_TESTS") != "1",
    reason="Opt-in actual Mac kernel observation; normal ABI mocks are not Mac qualification",
)
def test_actual_native_mac_memory_and_cpu():
    native = darwin._Native()
    assert native.physical_memory() > 0
    assert 0 <= native.free_memory() <= native.physical_memory()
    assert native.swap()[1] <= native.swap()[0]
    first = darwin.cpu()
    time.sleep(0.1)
    second = darwin.cpu()
    assert first["temperature_c"] is None and second["temperature_c"] is None
    assert second["utilization"] is None or 0 <= second["utilization"] <= 100
    assert darwin.memory()["status"] == "available"
