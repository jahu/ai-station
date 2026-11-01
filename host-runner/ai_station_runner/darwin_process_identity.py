"""Read-only Darwin process facts; never permission to launch, adopt or signal."""

import ctypes
import errno
import json
import os
import sys
from dataclasses import asdict, dataclass
from uuid import UUID


class _BSDInfo(ctypes.Structure):
    # Public PROC_PIDTBSDINFO layout, not a copied Linux /proc record. Keep
    # unused credential/name fields opaque; no process text leaves this probe.
    _fields_ = [
        ("prefix", ctypes.c_uint32 * 3),
        ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("credentials", ctypes.c_uint32 * 5),
        ("command", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("files", ctypes.c_uint32),
        ("pgid", ctypes.c_uint32),
        ("job", ctypes.c_uint32 * 4),
        ("started_seconds", ctypes.c_uint64),
        ("started_microseconds", ctypes.c_uint64),
    ]


@dataclass(frozen=True)
class DarwinIdentity:
    boot_id: str
    pid: int
    uid: int
    pgid: int
    session: int
    started_us: int
    state: int
    format: str = "darwin-bsdinfo-us-v1"


def _system_calls():
    if sys.platform != "darwin":
        raise OSError("Darwin process inspection requires native macOS")
    try:
        info = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True).proc_pidinfo
        boot = ctypes.CDLL(None, use_errno=True).sysctlbyname
    except (OSError, AttributeError) as exc:
        raise OSError("Native Darwin process inspection is unavailable") from exc
    info.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    info.restype = ctypes.c_int
    boot.argtypes = [
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    boot.restype = ctypes.c_int
    return info, boot


def _boot_uuid(query):
    buffer = ctypes.create_string_buffer(64)
    size = ctypes.c_size_t(len(buffer))
    # Only this fixed, read-only sysctl key; no caller-selected OS operation.
    ctypes.set_errno(0)
    if query(b"kern.bootsessionuuid", buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno() or errno.EIO, "Darwin boot identity is unavailable")
    if not 37 <= size.value <= len(buffer) or buffer.raw[size.value - 1] != 0:
        raise OSError("Darwin boot identity is incomplete")
    try:
        value = buffer.raw[: size.value - 1].decode("ascii")
        identity = UUID(value)
        if value.lower() != str(identity) or identity.int == 0:
            raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise OSError("Darwin boot identity is invalid") from exc
    return str(identity)


def _read(query, pid):
    result = _BSDInfo()
    ctypes.set_errno(0)
    size = ctypes.sizeof(result)
    if size != 136:
        raise OSError("Unsupported Darwin process-info ABI")
    returned = query(pid, 3, 0, ctypes.byref(result), size)
    if returned != size:
        error = ctypes.get_errno() or errno.EIO
        raise OSError(error, "Darwin process identity is incomplete or unavailable")
    if (
        result.pid != pid
        or not 0 < result.pgid < 2**31
        or not 1 <= result.prefix[1] <= 5
        or not 0 < result.started_seconds < 2**63
        or result.started_microseconds >= 1_000_000
    ):
        raise OSError("Darwin process identity is invalid")
    if result.uid != os.geteuid():
        raise PermissionError(errno.EACCES, "Darwin process belongs to another OS user")
    return result


def snapshot(pid: int) -> DarwinIdentity:
    if type(pid) is not int or not 0 < pid < 2**31:
        raise ValueError("A positive native process ID is required")
    query, boot_query = _system_calls()
    boot = _boot_uuid(boot_query)
    before = _read(query, pid)
    session = os.getsid(pid)
    after = _read(query, pid)
    fields = ("pid", "uid", "pgid", "started_seconds", "started_microseconds")
    if session <= 0 or any(getattr(before, field) != getattr(after, field) for field in fields):
        raise OSError(errno.ESTALE, "Darwin process changed during identity inspection")
    return DarwinIdentity(
        boot_id=boot,
        pid=pid,
        uid=after.uid,
        pgid=after.pgid,
        session=session,
        started_us=after.started_seconds * 1_000_000 + after.started_microseconds,
        state=after.prefix[1],
    )


if __name__ == "__main__":
    # Developer qualification only: inspect this process, never a supplied PID.
    if len(sys.argv) != 1:
        raise SystemExit("This probe inspects only itself and accepts no arguments")
    try:
        print(json.dumps(asdict(snapshot(os.getpid()))))
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
