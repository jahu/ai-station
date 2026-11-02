"""Connection health uses an actual private Unix HTTP peer, without Docker/AI."""

import asyncio
import shutil
import socket
import tempfile
import threading
from pathlib import Path

import desktop_connection as connection
import pytest


@pytest.fixture
def short_root():
    root = Path(tempfile.mkdtemp(prefix="asthealth-", dir="/tmp")).resolve()
    try:
        yield root
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, b'{"status":"ok","data_dir":"/private/native/data"}', True),
        (503, b'{"status":"ok"}', False),
        (200, b'{"status":"starting"}', False),
        (200, b'"ok"', False),
        (200, b"not JSON", False),
        (200, b'{"status":true}', False),
        (200, b'{"status":"ok","extra":"' + b"x" * 65536 + b'"}', False),
    ],
)
def test_health_requires_bounded_successful_native_runner_reply(
    short_root, monkeypatch, status, body, expected
):
    path = short_root / "runner.sock"
    monkeypatch.setattr(connection, "SOCKET", path)
    requests, errors = [], []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            try:
                client, _ = listener.accept()
                with client:
                    client.settimeout(5)
                    with client.makefile("rb") as reader:
                        request = b""
                        while not request.endswith(b"\r\n\r\n"):
                            request += reader.readline(4097)
                            assert len(request) <= 4096
                        requests.append(request)
                    client.sendall(
                        f"HTTP/1.1 {status} result\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                        + body
                    )
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            assert connection.health() is expected
        finally:
            thread.join(timeout=7)
        assert not thread.is_alive() and not errors
    assert len(requests) == 1 and requests[0].startswith(b"GET /health HTTP/1.1\r\n")
    assert b"Connection: close\r\n" in requests[0]


def test_missing_connection_is_unhealthy_without_creating_a_socket(short_root, monkeypatch):
    path = short_root / "missing.sock"
    monkeypatch.setattr(connection, "SOCKET", path)
    assert connection.health() is False and not path.exists()


@pytest.mark.parametrize(
    "value", [None, "", "0", "80", "65536", "-1200", "1234.0", "１２３４", "true", "1234;id"]
)
def test_missing_invalid_or_privileged_port_cannot_open_the_service(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("AI_STATION_NATIVE_CONNECTION_PORT", raising=False)
    else:
        monkeypatch.setenv("AI_STATION_NATIVE_CONNECTION_PORT", value)
    with pytest.raises(ValueError, match="supervisor-selected port"):
        connection.port()


@pytest.mark.parametrize("platform,uid", [("darwin", 501), ("linux", 0)])
def test_native_or_root_launch_is_refused_before_credentials_or_socket(monkeypatch, platform, uid):
    monkeypatch.setattr(connection.sys, "platform", platform)
    monkeypatch.setattr(connection.os, "geteuid", lambda: uid)
    with pytest.raises(ValueError, match="ordinary Linux container user"):
        asyncio.run(connection.serve())
