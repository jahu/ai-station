"""Internal Mac ProcessManager candidate; not selected by the normal Runner."""

import ctypes
import errno
import os
import signal
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from ai_station_runner import darwin_process_identity as kernel
from ai_station_runner.processes import ProcessManager

FORMAT = "darwin-bsdinfo-us-v1"
MAX_GROUP_MEMBERS = 8192


def group_members(pgid):
    if type(pgid) is not int or not 0 < pgid < 2**31:
        raise ValueError("A positive owned process group is required")
    if sys.platform != "darwin":
        raise OSError("Darwin group inspection requires native macOS")
    try:
        query = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True).proc_listpids
    except (OSError, AttributeError) as exc:
        raise OSError("Native process group inspection is unavailable") from exc
    query.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    query.restype = ctypes.c_int
    values = (ctypes.c_int * MAX_GROUP_MEMBERS)()
    size = ctypes.sizeof(values)
    ctypes.set_errno(0)
    returned = query(2, pgid, values, size)  # Fixed PROC_PGRP_ONLY, bytes not PID count.
    error = ctypes.get_errno()
    if returned < 0 or (returned == 0 and error):
        raise OSError(error or errno.EIO, "Native group inspection failed")
    if returned >= size or returned % ctypes.sizeof(ctypes.c_int):
        raise OSError(errno.EOVERFLOW, "Native group inspection is incomplete")
    result = tuple(values[: returned // ctypes.sizeof(ctypes.c_int)])
    if any(not 0 < pid < 2**31 for pid in result) or len(set(result)) != len(result):
        raise OSError("Native group inspection returned invalid process identities")
    return result


def _snapshot(pid):
    try:
        return kernel.snapshot(pid)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return None
        # Denied/incomplete facts must not release ownership or authorize a signal.
        raise


def group_alive(record):
    native = record.get("native_identity")
    if not isinstance(native, dict) or (
        native.get("format") != FORMAT
        or type(record.get("pid")) is not int
        or not 0 < record["pid"] < 2**31
        or native.get("pid") != record["pid"]
        or native.get("pgid") != record.get("process_group_id")
        or native.get("pgid") != record["pid"]
        or native.get("session") != record["pid"]
        or native.get("uid") != os.geteuid()
        or native.get("boot_id") != record.get("boot_id")
        or type(native.get("started_us")) is not int
        or native["started_us"] <= 0
    ):
        raise ValueError("A complete owned Darwin session journal is required")
    if kernel.snapshot(os.getpid()).boot_id != native["boot_id"]:
        return False
    leader = _snapshot(record["pid"])
    if leader and leader.started_us != native["started_us"]:
        return False  # The original leader PID was reused, never adopt its group.

    def belongs(value):
        return bool(
            value
            and value.format == FORMAT
            and value.boot_id == native["boot_id"]
            and value.uid == native["uid"]
            and value.pgid == native["pgid"]
            and value.session == native["session"]
            and value.started_us >= native["started_us"]
            and value.state in {1, 2, 3, 4}  # SZOMB=5 never proves live work.
        )

    if belongs(leader):
        return True
    for pid in group_members(native["pgid"]):
        if belongs(_snapshot(pid)):
            return True
    return False


class DarwinProcessManager(ProcessManager):
    @staticmethod
    def _boot_identity():
        # Preflight the actual read-only ABI/credentials before launching a gate.
        return kernel.snapshot(os.getpid()).boot_id

    @staticmethod
    def _capture_identity(pid, boot_id):
        value = kernel.snapshot(pid)
        if (
            value.boot_id != boot_id
            or value.pid != pid
            or value.uid != os.geteuid()
            or value.format != FORMAT
            or value.started_us <= 0
            or value.state not in {1, 2, 3, 4}
            or value.pid != value.pgid
            or value.pid != value.session
        ):
            raise OSError("The new native child is not the expected owned session leader")
        return {"native_identity": asdict(value)}

    @staticmethod
    def _process_alive(record):
        return group_alive(record)

    @contextmanager
    def _launch(self, argv, *, cwd, env, stdout, stderr):
        read, write = os.pipe()
        proc = None
        try:
            gate = Path(__file__).with_name("process_gate.py").resolve(strict=True)
            proc = subprocess.Popen(
                [sys.executable, "-I", "-S", "-B", str(gate), str(read), *argv],
                cwd=cwd,
                env=env,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                pass_fds=(read,),
                umask=0o077,
            )
            os.close(read)
            read = None
            yield proc  # The shared manager durably publishes identity here.
            os.write(write, b"1")
        except BaseException:
            # This is the immediate, unreaped Popen child in our new session,
            # not a PID recovered from a journal or supplied by a caller.
            if proc is not None and proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
            raise
        finally:
            if read is not None:
                os.close(read)
            os.close(write)
