"""Private UDS/mutual-TLS connection primitives; not consumer admission or a Runner API."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import select
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from desktop_control import private_socket, same_user  # noqa: E402

SERVER_NAME = "host.docker.internal"
MAX_CONNECTIONS = 32
CONNECTION_SECONDS = 3600


def directory(path):
    path = Path(path)
    value = path.lstat()
    if (
        path.resolve(strict=True) != path
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_mode & 0o077
    ):
        raise ValueError("Connection storage must be a canonical private owned directory")
    return path


def private_file(path):
    value = path.lstat()
    if (
        path.resolve(strict=True) != path
        or not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_nlink != 1
        or value.st_mode & 0o077
    ):
        raise ValueError("Connection credentials and receipts must remain private owned regular files")
    return path


def prepare_credentials(output):
    """One new private generation; fixed OS OpenSSL calls, no global trust change."""
    output = Path(output)
    directory(output.parent)
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a new connection credential generation")
    output.mkdir(mode=0o700)
    for role in ("server", "client"):
        (output / role).mkdir(mode=0o700)

    def write(path, text):
        with path.open("x") as file:
            os.fchmod(file.fileno(), 0o600)
            file.write(text)

    common = "[req]\nprompt=no\ndistinguished_name=dn\n[dn]\nCN=AI Station private connection\n"
    write(
        output / "ca.cnf",
        common
        + "[ca]\nbasicConstraints=critical,CA:true\n"
        + "keyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n",
    )
    write(output / "request.cnf", common)

    def openssl(*args):
        result = subprocess.run(
            ["/usr/bin/openssl", *args],
            cwd=output,
            env={"PATH": os.defpath, "HOME": str(output), "LANG": "C"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Private connection certificate preparation failed")

    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-sha256",
        "-nodes",
        "-days",
        "3650",
        "-config",
        "ca.cnf",
        "-extensions",
        "ca",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
    )
    for serial, role in enumerate(("server", "client"), 1):
        openssl(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-config",
            "request.cnf",
            "-subj",
            "/CN=" + (SERVER_NAME if role == "server" else "AI Station control plane"),
            "-keyout",
            role + "/key.pem",
            "-out",
            role + ".csr",
        )
        extensions = (
            "basicConstraints=critical,CA:false\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nextendedKeyUsage="
            + (
                "serverAuth\nsubjectAltName=DNS:host.docker.internal,IP:127.0.0.1\n"
                if role == "server"
                else "clientAuth\n"
            )
        )
        write(output / (role + ".cnf"), extensions)
        openssl(
            "x509",
            "-req",
            "-in",
            role + ".csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-set_serial",
            str(serial),
            "-sha256",
            "-days",
            "3650",
            "-extfile",
            role + ".cnf",
            "-out",
            role + "/cert.pem",
        )
        (output / role / "ca.pem").write_bytes((output / "ca.crt").read_bytes())
        for filename in ("key.pem", "cert.pem", "ca.pem"):
            (output / role / filename).chmod(0o400)
    fingerprint = hashlib.sha256((output / "ca.crt").read_bytes()).hexdigest()
    # Runtime peers receive no issuer key or request/build files.
    for name in (
        "ca.key",
        "ca.crt",
        "ca.cnf",
        "request.cnf",
        "server.csr",
        "client.csr",
        "server.cnf",
        "client.cnf",
    ):
        (output / name).unlink()
    return {"ca_sha256": fingerprint, "consumer_installer_qualified": False}


def context(root, *, server):
    root = directory(root)
    for name in ("ca.pem", "cert.pem", "key.pem"):
        private_file(root / name)
    if server:
        value = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        value.verify_mode = ssl.CERT_REQUIRED
        value.load_verify_locations(cafile=root / "ca.pem")
    else:
        value = ssl.create_default_context(cafile=root / "ca.pem")
    value.minimum_version = ssl.TLSVersion.TLSv1_2
    value.load_cert_chain(root / "cert.pem", root / "key.pem")
    return value


async def close(writer):
    writer.close()
    with suppress(OSError, TimeoutError):
        async with asyncio.timeout(2):
            await writer.wait_closed()


async def relay(left, right, *, half_close=False):
    async def copy(reader, writer):
        while block := await reader.read(65536):
            writer.write(block)
            await writer.drain()

    jobs = [asyncio.create_task(copy(left[0], right[1])), asyncio.create_task(copy(right[0], left[1]))]
    try:
        async with asyncio.timeout(CONNECTION_SECONDS):
            done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for job in done:
                job.result()
            if half_close and jobs[0] in done and jobs[1] not in done:
                # A Unix HTTP client may finish writing before receiving its
                # response. TLS has no write_eof; retain the return path until
                # the server finishes instead of discarding the response.
                await jobs[1]
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


@asynccontextmanager
async def serving(start, opener, *, half_close=False):
    tasks = set()

    async def connected(reader, writer):
        if len(tasks) >= MAX_CONNECTIONS:
            await close(writer)
            return
        current = asyncio.current_task()
        tasks.add(current)
        remote = None
        try:
            async with asyncio.timeout(5):
                remote = await opener(writer)
            await relay((reader, writer), remote, half_close=half_close)
        except (OSError, ValueError, TimeoutError):
            # No request, certificate, secret or model output enters logs.
            pass
        finally:
            if remote is not None:
                await close(remote[1])
            await close(writer)
            tasks.discard(current)

    server = await start(connected)
    try:
        yield server
    finally:
        server.close()
        await server.wait_closed()
        for task in tuple(tasks):
            task.cancel()
        await asyncio.gather(*tuple(tasks), return_exceptions=True)


@asynccontextmanager
async def native(credentials, runner_socket):
    if os.geteuid() == 0:
        raise ValueError("The native connection must run as an ordinary user")
    runner_socket = Path(runner_socket)
    directory(runner_socket.parent)
    original = private_socket(runner_socket)
    if runner_socket.resolve(strict=True) != runner_socket:
        raise ValueError("The native Runner socket must remain canonical")
    tls = context(credentials, server=True)

    async def open_runner(_incoming):
        current = private_socket(runner_socket)
        if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
            raise ValueError("The frozen native Runner socket changed")
        reader, writer = await asyncio.open_unix_connection(str(runner_socket))
        if not same_user(writer.get_extra_info("socket")):
            await close(writer)
            raise PermissionError("The native Runner peer differs")
        return reader, writer

    async def start(callback):
        return await asyncio.start_server(
            callback,
            "127.0.0.1",
            0,
            family=socket.AF_INET,
            ssl=tls,
            ssl_handshake_timeout=5,
            ssl_shutdown_timeout=2,
            backlog=16,
        )

    async with serving(start, open_runner) as server:
        yield server.sockets[0].getsockname()[1]


@contextmanager
def owned_socket(path):
    path = Path(path)
    directory(path.parent)
    lock = path.with_name(path.name + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    record = path.with_name(path.name + ".json")
    created = None
    try:
        info = private_file(lock).stat()
        opened = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Connection socket lock changed")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = private_file(lock).stat()
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Connection socket lock changed")
        previous = None
        if record.exists() or record.is_symlink():
            private_file(record)
            if record.stat().st_size > 4096:
                raise ValueError("Connection socket receipt exceeded its bound")
            previous = json.loads(record.read_text())
            if (
                not isinstance(previous, dict)
                or set(previous) != {"schema", "device", "inode"}
                or type(previous["schema"]) is not int
                or previous["schema"] != 1
                or any(type(previous[key]) is not int or previous[key] < 0 for key in ("device", "inode"))
            ):
                raise ValueError("The connection socket receipt needs inspection")
        if path.exists() or path.is_symlink():
            value = private_socket(path)
            if previous != {"schema": 1, "device": value.st_dev, "inode": value.st_ino}:
                raise ValueError("Unrecognized connection socket was preserved")
            path.unlink()

        def remember():
            nonlocal created
            path.chmod(0o600)
            value = private_socket(path)
            created = (value.st_dev, value.st_ino)
            temporary, name = tempfile.mkstemp(prefix=".link-", dir=path.parent)
            try:
                with os.fdopen(temporary, "w") as file:
                    json.dump({"schema": 1, "device": value.st_dev, "inode": value.st_ino}, file)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(name, record)
            finally:
                Path(name).unlink(missing_ok=True)

        yield remember
    finally:
        try:
            if created is not None:
                try:
                    value = private_socket(path)
                    if (value.st_dev, value.st_ino) == created:
                        path.unlink()
                except FileNotFoundError:
                    pass
        finally:
            os.close(fd)


@asynccontextmanager
async def proxy(credentials, local_socket, port, *, host=SERVER_NAME):
    if os.geteuid() == 0:
        raise ValueError("The control-plane connection must run as an ordinary user")
    if host not in {SERVER_NAME, "127.0.0.1"} or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Use the frozen local Mac connection coordinates")
    tls = context(credentials, server=False)

    async def connect(incoming):
        if not same_user(incoming.get_extra_info("socket")):
            raise PermissionError("The control-plane socket peer differs")
        return await asyncio.open_connection(
            host,
            port,
            ssl=tls,
            server_hostname=SERVER_NAME,
            ssl_handshake_timeout=5,
            ssl_shutdown_timeout=2,
        )

    async def start(callback):
        return await asyncio.start_unix_server(callback, path=str(local_socket), backlog=16)

    with owned_socket(local_socket) as remember:
        async with serving(start, connect, half_close=True):
            remember()
            yield


class NativeOwner:
    """Immediate owned helper plus an inherited pipe, never persisted-PID signaling."""

    def __init__(self, credentials, runner_socket):
        self.credentials = directory(credentials)
        self.runner_socket = Path(runner_socket)
        self.process = None
        self.parent = None
        self.port = None

    def start(self):
        if self.process is not None:
            raise ValueError("A native connection owner cannot be started twice")
        read_parent = ready = write_ready = None
        try:
            read_parent, self.parent = os.pipe()
            ready, write_ready = os.pipe()
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-IB",
                    str(Path(__file__).resolve()),
                    "--native",
                    "--credentials",
                    str(self.credentials),
                    "--socket",
                    str(self.runner_socket),
                    "--parent-fd",
                    str(read_parent),
                    "--ready-fd",
                    str(write_ready),
                ],
                pass_fds=(read_parent, write_ready),
                env={"PATH": os.defpath, "HOME": str(self.credentials.parent), "LANG": "C"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.close(read_parent)
            read_parent = None
            os.close(write_ready)
            write_ready = None
            data = b""
            deadline = time.monotonic() + 10
            while not data.endswith(b"\n"):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.process.poll() is not None:
                    raise RuntimeError("The private native connection did not become ready")
                if select.select([ready], [], [], remaining)[0]:
                    block = os.read(ready, 257 - len(data))
                    if not block or len(data) + len(block) > 256:
                        raise ValueError("Invalid private connection readiness frame")
                    data += block
            value = json.loads(data)
            expected = hashlib.sha256((self.credentials / "ca.pem").read_bytes()).hexdigest()
            if (
                not isinstance(value, dict)
                or set(value) != {"port", "ca_sha256"}
                or type(value.get("port")) is not int
                or not 1024 <= value["port"] <= 65535
                or value.get("ca_sha256") != expected
            ):
                raise ValueError("The native connection readiness identity differs")
            self.port = value["port"]
            return self
        except BaseException:
            self.close()
            raise
        finally:
            for fd in (read_parent, write_ready, ready):
                if fd is not None:
                    os.close(fd)

    def close(self):
        if self.parent is not None:
            os.close(self.parent)
            self.parent = None
        if self.process is not None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)


async def native_main(args):
    for fd, access in ((args.parent_fd, os.O_RDONLY), (args.ready_fd, os.O_WRONLY)):
        if (
            fd <= 2
            or not stat.S_ISFIFO(os.fstat(fd).st_mode)
            or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != access
        ):
            raise ValueError("Native supervision requires its actual private parent pipes")
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    os.set_blocking(args.parent_fd, False)

    def parent_closed():
        try:
            if not os.read(args.parent_fd, 1):
                done.set()
        except BlockingIOError:
            pass

    loop.add_reader(args.parent_fd, parent_closed)
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, done.set)
    try:
        async with native(args.credentials, args.socket) as port:
            value = {
                "port": port,
                "ca_sha256": hashlib.sha256((args.credentials / "ca.pem").read_bytes()).hexdigest(),
            }
            os.write(args.ready_fd, json.dumps(value).encode() + b"\n")
            os.close(args.ready_fd)
            await done.wait()
    finally:
        loop.remove_reader(args.parent_fd)
        os.close(args.parent_fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--parent-fd", type=int, required=True)
    parser.add_argument("--ready-fd", type=int, required=True)
    asyncio.run(native_main(parser.parse_args()))
