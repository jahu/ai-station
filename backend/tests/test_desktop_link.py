"""Real UDS and mutual TLS with neutral HTTP; no Docker, model or Runner."""

import asyncio
import fcntl
import json
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import desktop_link as link
import pytest


@pytest.fixture(scope="module")
def credentials():
    root = Path(tempfile.mkdtemp(prefix="astlink-", dir="/tmp")).resolve()
    try:
        proof = link.prepare_credentials(root / "credentials")
        assert len(proof["ca_sha256"]) == 64 and proof["consumer_installer_qualified"] is False
        assert sorted(p.name for p in (root / "credentials").iterdir()) == ["client", "server"]
        for role in ("client", "server"):
            for path in (root / "credentials" / role).iterdir():
                assert path.stat().st_mode & 0o777 == 0o400
        yield root / "credentials"
    finally:
        shutil.rmtree(root)


@pytest.fixture
def short_root():
    root = Path(tempfile.mkdtemp(prefix="astconn-", dir="/tmp")).resolve()
    try:
        yield root
    finally:
        shutil.rmtree(root)


@asynccontextmanager
async def backend(path, observed, body=b'{"status":"ok"}'):
    async def request(reader, writer):
        try:
            observed.append(await reader.readuntil(b"\r\n\r\n"))
            await asyncio.sleep(0.03)
            writer.write(
                b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
            )
            for offset in range(0, len(body), 997):
                writer.write(body[offset : offset + 997])
                await writer.drain()
        finally:
            await link.close(writer)

    server = await asyncio.start_unix_server(request, path=str(path))
    path.chmod(0o600)
    try:
        yield
    finally:
        server.close()
        await server.wait_closed()
        path.unlink(missing_ok=True)


def test_real_connection_preserves_concurrent_streams_and_half_closed_requests(credentials, short_root):
    body = 'data: {"delta":"Zażółć gęślą jaźń"}\n\n'.encode() * 2000
    observed = []

    async def scenario():
        target, local = short_root / "runner.sock", short_root / "client.sock"
        async with backend(target, observed, body):
            async with link.native(credentials / "server", target) as port:
                async with link.proxy(credentials / "client", local, port, host="127.0.0.1"):

                    async def get(half_close):
                        reader, writer = await asyncio.open_unix_connection(str(local))
                        writer.write(b"GET /health HTTP/1.1\r\nHost: runner\r\n\r\n")
                        await writer.drain()
                        if half_close:
                            writer.write_eof()
                        raw = await asyncio.wait_for(reader.read(), timeout=10)
                        assert raw.split(b"\r\n\r\n", 1)[1] == body
                        await link.close(writer)

                    await asyncio.gather(*(get(bool(i % 2)) for i in range(8)))
                assert not local.exists()
        assert len(observed) == 8

    asyncio.run(scenario())


@pytest.mark.parametrize("foreign", [False, True])
def test_missing_or_foreign_client_certificate_cannot_reach_runner(credentials, short_root, foreign):
    observed = []
    client = ssl.create_default_context(cafile=credentials / "client/ca.pem")
    if foreign:
        other = short_root / "foreign"
        link.prepare_credentials(other)
        client.load_cert_chain(other / "client/cert.pem", other / "client/key.pem")

    async def scenario():
        path = short_root / "runner.sock"
        async with backend(path, observed):
            async with link.native(credentials / "server", path) as port:
                writer = None
                try:
                    reader, writer = await asyncio.open_connection(
                        "127.0.0.1", port, ssl=client, server_hostname=link.SERVER_NAME
                    )
                    writer.write(b"GET /health HTTP/1.1\r\nHost: runner\r\n\r\n")
                    await writer.drain()
                    assert await asyncio.wait_for(reader.read(), timeout=3) == b""
                except (ssl.SSLError, ConnectionError):
                    pass
                finally:
                    if writer is not None:
                        await link.close(writer)
                assert not observed

    asyncio.run(scenario())


def test_other_unix_peer_cannot_reach_connection(credentials, short_root, monkeypatch):
    observed = []
    monkeypatch.setattr(link, "same_user", lambda _: False)

    async def scenario():
        target, local = short_root / "runner.sock", short_root / "client.sock"
        async with backend(target, observed):
            async with link.native(credentials / "server", target) as port:
                async with link.proxy(credentials / "client", local, port, host="127.0.0.1"):
                    reader, writer = await asyncio.open_unix_connection(str(local))
                    assert await asyncio.wait_for(reader.read(), timeout=3) == b""
                    await link.close(writer)
                assert not observed

    asyncio.run(scenario())


def test_replaced_runner_socket_is_not_adopted(credentials, short_root):
    original, replacement = [], []

    async def scenario():
        path, local = short_root / "runner.sock", short_root / "client.sock"
        async with backend(path, original):
            async with link.native(credentials / "server", path) as port:
                path.unlink()
                async with backend(path, replacement):
                    async with link.proxy(credentials / "client", local, port, host="127.0.0.1"):
                        reader, writer = await asyncio.open_unix_connection(str(local))
                        writer.write(b"GET /health HTTP/1.1\r\nHost: runner\r\n\r\n")
                        await writer.drain()
                        assert await asyncio.wait_for(reader.read(), timeout=3) == b""
                        await link.close(writer)
                    assert not original and not replacement

    asyncio.run(scenario())


def test_credentials_cannot_escape_or_be_shared_and_are_not_repaired(credentials, short_root):
    root = short_root / "client"
    shutil.copytree(credentials / "client", root)
    target = root / "key.pem"
    content = target.read_bytes()
    target.chmod(0o644)
    with pytest.raises(ValueError, match="private owned regular"):
        link.context(root, server=False)
    assert target.stat().st_mode & 0o777 == 0o644
    target.unlink()
    target.symlink_to(credentials / "client/key.pem")
    with pytest.raises(ValueError, match="private owned regular"):
        link.context(root, server=False)
    assert (credentials / "client/key.pem").read_bytes() == content


def test_unknown_socket_is_preserved_and_lock_released(short_root):
    path = short_root / "client.sock"
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        path.chmod(0o600)
        original = path.stat().st_ino
        with pytest.raises(ValueError, match="Unrecognized"):
            with link.owned_socket(path):
                pytest.fail("Unknown socket adopted")
        assert path.stat().st_ino == original
        with path.with_name(path.name + ".lock").open("rb") as file:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_live_owner_and_replaced_file_survive_cleanup(short_root):
    path = short_root / "client.sock"
    with pytest.raises(ValueError, match="private owned socket"):
        with link.owned_socket(path) as remember:
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path))
                remember()
                with pytest.raises(BlockingIOError):
                    with link.owned_socket(path):
                        pytest.fail("Concurrent owner started")
                path.unlink()
                path.write_text("preserve unrelated replacement")
                path.chmod(0o600)
    assert path.read_text() == "preserve unrelated replacement"
    with path.with_name(path.name + ".lock").open("rb") as file:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_actual_owner_exit_allows_only_confirmed_stale_socket_recovery(short_root):
    path = short_root / "client.sock"
    code = """import os,socket,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import desktop_link
path=Path(sys.argv[2])
with desktop_link.owned_socket(path) as remember:
 s=socket.socket(socket.AF_UNIX);s.bind(str(path));remember();os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-IB", "-c", code, str(Path(link.__file__).parent), str(path)], check=True, timeout=5
    )
    assert path.is_socket()
    with link.owned_socket(path):
        assert not path.exists()


def test_native_child_stops_on_pipe_eof_and_preserves_the_runner(credentials, short_root):
    path = short_root / "runner.sock"
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        server.listen(1)
        path.chmod(0o600)
        original = path.stat().st_ino
        owner = link.NativeOwner(credentials / "server", path).start()
        assert owner.process.poll() is None
        owner.close()
        assert owner.process.returncode == 0 and path.stat().st_ino == original
        with socket.socket(socket.AF_INET) as client:
            assert client.connect_ex(("127.0.0.1", owner.port)) != 0
        owner.close()  # Completed handles are safe to close again.


def test_actual_parent_exit_closes_the_native_listener_without_recorded_pid_signals(credentials, short_root):
    proof = short_root / "ready.json"
    code = """import json,os,socket,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import desktop_link
root=Path(sys.argv[3]);path=root/'runner.sock'
s=socket.socket(socket.AF_UNIX);s.bind(str(path));s.listen(1);path.chmod(0o600)
owner=desktop_link.NativeOwner(Path(sys.argv[2]),path).start()
(root/'ready.json').write_text(json.dumps({'port':owner.port}))
os._exit(0)
"""
    subprocess.run(
        [
            sys.executable,
            "-IB",
            "-c",
            code,
            str(Path(link.__file__).parent),
            str(credentials / "server"),
            str(short_root),
        ],
        check=True,
        timeout=15,
    )
    port = json.loads(proof.read_text())["port"]
    deadline = time.monotonic() + 5
    while True:
        with socket.socket(socket.AF_INET) as client:
            if client.connect_ex(("127.0.0.1", port)) != 0:
                break
        assert time.monotonic() < deadline, "Native helper outlived its actual parent"
        time.sleep(0.02)


@pytest.mark.parametrize(
    "host,port", [("0.0.0.0", 8080), ("remote.invalid", 8080), ("127.0.0.1", True), ("127.0.0.1", 80)]
)
def test_public_targets_and_privileged_ports_fail_before_any_file_creation(short_root, host, port):
    async def scenario():
        with pytest.raises(ValueError, match="frozen local Mac"):
            async with link.proxy(short_root / "absent", short_root / "never.sock", port, host=host):
                pytest.fail("Invalid target")
        assert not (short_root / "never.sock").exists()

    asyncio.run(scenario())
