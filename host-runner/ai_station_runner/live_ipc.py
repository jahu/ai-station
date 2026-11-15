"""Bounded local media pipes and immutable, memory-only reference snapshots."""

import asyncio
import ctypes
import fcntl
import hashlib
import hmac
import os
import signal
import stat
import struct

PREFIX = struct.Struct("!I")
CLOCK = struct.Struct("!IQ")
MAX_IPC_BYTES = 512 * 1024 + 128


def bind_parent(expected):
    if type(expected) is not int or expected <= 1 or os.getppid() != expected:
        raise ValueError("A live inference child requires its original owned parent")
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot bind live child lifetime")
    if os.getppid() != expected:
        raise InterruptedError("The native live parent exited during child startup")


def memory_snapshot(data):
    if not isinstance(data, bytes) or not 1 <= len(data) <= 20 * 1024**2:
        raise ValueError("Live references require a bounded memory snapshot")
    fd = os.memfd_create("ai-station-live-reference", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        with os.fdopen(os.dup(fd), "wb") as target:
            target.write(data)
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, getattr(fcntl, "F_ADD_SEALS", 1033), 0x0F)
    except BaseException:
        os.close(fd)
        raise
    return fd


def snapshot_bytes(fd, digest):
    if type(fd) is not int or fd < 3:
        raise ValueError("A live reference needs its inherited memory descriptor")
    info = os.fstat(fd)
    if (
        os.readlink(f"/proc/self/fd/{fd}") != "/memfd:ai-station-live-reference (deleted)"
        or fcntl.fcntl(fd, getattr(fcntl, "F_GET_SEALS", 1034)) & 0x0F != 0x0F
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 0
        or not 1 <= info.st_size <= 20 * 1024**2
    ):
        raise ValueError("Live reference must remain an immutable memory snapshot")
    data = os.pread(fd, info.st_size, 0)
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), digest):
        raise ValueError("Live reference identity changed")
    return data


def read_sync(source):
    def exact(count):
        chunks = bytearray()
        while len(chunks) < count:
            chunk = source.read(count - len(chunks))
            if not chunk:
                if not chunks and count == PREFIX.size:
                    return None
                raise EOFError("Truncated live inference packet")
            chunks.extend(chunk)
        return bytes(chunks)

    header = exact(PREFIX.size)
    if header is None:
        return None
    size = PREFIX.unpack(header)[0]
    if not 0 < size <= MAX_IPC_BYTES:
        raise ValueError("Local live packet exceeds its bound")
    return exact(size)


def write_sync(target, payload):
    if not 0 < len(payload) <= MAX_IPC_BYTES:
        raise ValueError("Local live packet exceeds its bound")
    target.write(PREFIX.pack(len(payload)) + payload)
    target.flush()


async def read_async(reader):
    size = PREFIX.unpack(await reader.readexactly(PREFIX.size))[0]
    if not 0 < size <= MAX_IPC_BYTES:
        raise ValueError("Local live packet exceeds its bound")
    return await reader.readexactly(size)


async def write_async(writer, payload):
    if not 0 < len(payload) <= MAX_IPC_BYTES:
        raise ValueError("Local live packet exceeds its bound")
    writer.write(PREFIX.pack(len(payload)) + payload)
    await asyncio.wait_for(writer.drain(), 2)
