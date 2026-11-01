"""Read-only native Mac observations, not memory enforcement or a Metal budget."""

import ctypes
import errno
import sys
import threading
from contextlib import contextmanager


class _VM(ctypes.Structure):
    # Public vm_statistics64 ABI. Unused cumulative counters remain opaque.
    _fields_ = [
        ("free_pages", ctypes.c_uint32),
        ("active_pages", ctypes.c_uint32),
        ("inactive_pages", ctypes.c_uint32),
        ("wired_pages", ctypes.c_uint32),
        ("cumulative", ctypes.c_uint64 * 9),
        ("purgeable_pages", ctypes.c_uint32),
        ("speculative_pages", ctypes.c_uint32),
        ("compression_counters", ctypes.c_uint64 * 4),
        ("compressed_pages", ctypes.c_uint32),
        ("other_counts", ctypes.c_uint32 * 3),
        ("uncompressed_pages", ctypes.c_uint64),
        ("swapped_pages", ctypes.c_uint64),
    ]


class _Swap(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_uint64),
        ("available", ctypes.c_uint64),
        ("used", ctypes.c_uint64),
        ("page_size", ctypes.c_uint32),
        ("encrypted", ctypes.c_uint32),
    ]


def _function(library, name, arguments, result):
    function = getattr(library, name)
    function.argtypes = arguments
    function.restype = result
    return function


class _Native:
    def __init__(self):
        if sys.platform != "darwin":
            raise OSError("Native Mac telemetry requires macOS")
        if ctypes.sizeof(_VM) != 160 or ctypes.sizeof(_Swap) != 32:
            raise OSError("Unsupported native telemetry ABI")
        try:
            library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
            self.task = ctypes.c_uint32.in_dll(library, "mach_task_self_").value
            self.host = _function(library, "mach_host_self", [], ctypes.c_uint32)
            self.release = _function(
                library, "mach_port_deallocate", [ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int
            )
            signature = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            self.statistics = _function(library, "host_statistics", signature, ctypes.c_int)
            self.statistics64 = _function(library, "host_statistics64", signature, ctypes.c_int)
            self.page_size = _function(
                library, "host_page_size", [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_int
            )
            self.sysctl = _function(
                library,
                "sysctlbyname",
                [
                    ctypes.c_char_p,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_size_t),
                    ctypes.c_void_p,
                    ctypes.c_size_t,
                ],
                ctypes.c_int,
            )
        except (OSError, AttributeError, ValueError) as exc:
            raise OSError("Native Mac telemetry is unavailable") from exc
        if not self.task:
            raise OSError("Native Mac task identity is unavailable")

    @contextmanager
    def host_port(self):
        port = self.host()
        if not port:
            raise OSError("Native Mac host observation is unavailable")
        try:
            yield port
        finally:
            if self.release(self.task, port) != 0:
                raise OSError("Native Mac host port could not be released")

    def physical_memory(self):
        value = ctypes.c_uint64()
        self._sysctl(b"hw.memsize", value)
        if not 0 < value.value <= 2**60:
            raise OSError("Invalid native physical memory observation")
        return value.value

    def swap(self):
        value = _Swap()
        self._sysctl(b"vm.swapusage", value)
        if (
            not 0 <= value.used <= value.total <= 2**60
            or value.available + value.used != value.total
            or value.encrypted not in {0, 1}
        ):
            raise OSError("Invalid native swap observation")
        return value.total, value.used

    def _sysctl(self, key, value):
        size = ctypes.c_size_t(ctypes.sizeof(value))
        ctypes.set_errno(0)
        if self.sysctl(key, ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
            raise OSError(ctypes.get_errno() or errno.EIO, "Native memory observation is unavailable")
        if size.value != ctypes.sizeof(value):
            raise OSError("Incomplete native memory observation")

    def memory_pages(self):
        with self.host_port() as port:
            page = ctypes.c_uint32()
            if self.page_size(port, ctypes.byref(page)) != 0:
                raise OSError("Native page size is unavailable")
            if not 4096 <= page.value <= 65536 or page.value & (page.value - 1):
                raise OSError("Invalid native page size")
            value = _VM()
            count = ctypes.c_uint32(ctypes.sizeof(value) // 4)
            if self.statistics64(port, 4, ctypes.byref(value), ctypes.byref(count)) != 0:
                raise OSError("Native VM statistics are unavailable")
            # Public rev1 is 38 words, rev2 adds one uint64_t. Accept only
            # complete public layouts, not a truncated/torn counter.
            if count.value not in {38, 40}:
                raise OSError("Incomplete native VM statistics")
            # Free and inactive are disjoint queues. Speculative pages are
            # already included in free; purgeable/compressed are not additions.
            return value.free_pages * page.value, value.inactive_pages * page.value

    def free_memory(self):
        return self.memory_pages()[0]

    def cpu_ticks(self):
        with self.host_port() as port:
            value = (ctypes.c_uint32 * 4)()
            count = ctypes.c_uint32(4)
            if self.statistics(port, 3, value, ctypes.byref(count)) != 0 or count.value != 4:
                raise OSError("Native CPU statistics are unavailable")
            return tuple(value)


_previous_cpu = None
_cpu_lock = threading.Lock()


def cpu():
    global _previous_cpu
    percent = None
    with _cpu_lock:
        try:
            current = _Native().cpu_ticks()
        except OSError:
            _previous_cpu = None
            return {"utilization": None, "temperature_c": None}
        if _previous_cpu is not None:
            deltas = [(new - old) % 2**32 for new, old in zip(current, _previous_cpu, strict=True)]
            total = sum(deltas)
            if total and all(value < 2**31 for value in deltas):
                # CPU_STATE_IDLE is index 2 (user/system/idle/nice).
                percent = round(100 * (1 - deltas[2] / total), 1)
        _previous_cpu = current
    return {"utilization": percent, "temperature_c": None}


def memory():
    result = dict.fromkeys(
        (
            "total_mib",
            "used_mib",
            "available_mib",
            "free_mib",
            "inactive_mib",
            "swap_used_mib",
            "swap_total_mib",
        )
    )
    result.update(
        available_basis="darwin_free_plus_inactive_pages", available_is_estimate=True, status="unavailable"
    )
    try:
        native = _Native()
    except OSError:
        return result
    try:
        total = native.physical_memory()
        result["total_mib"] = round(total / 1024**2, 1)
        free, inactive = native.memory_pages()
        available = free + inactive
        if not 0 <= free <= available <= total:
            raise OSError("Native memory queues exceed physical capacity")
        result.update(
            used_mib=round((total - available) / 1024**2, 1),
            available_mib=round(available / 1024**2, 1),
            free_mib=round(free / 1024**2, 1),
            inactive_mib=round(inactive / 1024**2, 1),
        )
    except OSError:
        pass
    try:
        total, used = native.swap()
        result.update(swap_total_mib=round(total / 1024**2, 1), swap_used_mib=round(used / 1024**2, 1))
    except OSError:
        pass
    known = [
        result[key] is not None
        for key in ("total_mib", "used_mib", "available_mib", "swap_used_mib", "swap_total_mib")
    ]
    result["status"] = "available" if all(known) else "partial" if any(known) else "unavailable"
    return result
