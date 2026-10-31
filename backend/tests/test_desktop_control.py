"""Real private IPC has only status and generation-bound stop, never host tools."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import desktop_control as control
import pytest
from ai_station_runner.unix_sockets import unix_address


def raw(root, value):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        with unix_address(root / control.CONTROL_FILE) as address:
            client.connect(address)
        client.sendall(value)
        client.shutdown(socket.SHUT_WR)
        return client.recv(1024)


@pytest.mark.parametrize("long", [False, True])
def test_real_status_and_instance_bound_stop_from_an_independent_process(tmp_path, long):
    root = tmp_path / ("long-owned-desktop-folder-" * 5 if long else "owned")
    root.mkdir(mode=0o700)
    with control.DesktopControl(root) as owner:
        owner.ready.set()
        owner.background.set()
        assert owner.path.stat().st_mode & 0o777 == 0o600
        status = control.request(root)
        assert status == owner.status() and status["background"] and status["ready"]
        scripts = Path(control.__file__).resolve().parent
        code = (
            "import sys;sys.path[:0]="
            + repr([str(scripts), str(scripts.parent / "host-runner")])
            + ";import desktop_control;from pathlib import Path;"
            + "assert desktop_control.request(Path(sys.argv[1]),'stop',instance_id=sys.argv[2])['accepted']"
        )
        subprocess.run(
            [sys.executable, "-I", "-c", code, str(root), owner.instance_id], check=True, timeout=10
        )
        assert owner.stop_requested.is_set()
        assert control.request(root)["stopping"]
    assert not owner.path.exists() and not owner.thread.is_alive()


@pytest.mark.parametrize(
    "value",
    [
        {"action": "shell", "command": "anything"},
        {"action": "stop"},
        {"action": "stop", "instance_id": "a" * 32},
        {"action": "status", "url": "https://example.com"},
        ["stop"],
    ],
)
def test_untyped_or_stale_requests_never_stop_the_owner(tmp_path, value):
    with control.DesktopControl(tmp_path) as owner:
        response = json.loads(raw(tmp_path, json.dumps(value).encode() + b"\n"))
        assert "error" in response and not owner.stop_requested.is_set()
        assert control.request(tmp_path) == owner.status()


@pytest.mark.parametrize("value", [b"x" * 129, b"\xff\n", b"{", b"not-json\n"])
def test_malformed_or_oversized_peer_is_bounded_and_does_not_break_next_client(tmp_path, value):
    with control.DesktopControl(tmp_path) as owner:
        assert raw(tmp_path, value) == b""
        assert control.request(tmp_path) == owner.status()
        assert not owner.stop_requested.is_set()


def test_previous_instance_cannot_stop_a_new_owner_at_the_same_socket(tmp_path):
    with control.DesktopControl(tmp_path) as previous:
        old = previous.instance_id
    with control.DesktopControl(tmp_path) as owner:
        assert owner.instance_id != old
        with pytest.raises(ValueError, match="instance changed"):
            control.request(tmp_path, "stop", instance_id=old)
        assert not owner.stop_requested.is_set()


@pytest.mark.parametrize("kind", ["symlink", "regular", "fifo", "public-socket"])
def test_unsafe_control_file_is_never_overwritten_or_connected(tmp_path, kind):
    path = tmp_path / control.CONTROL_FILE
    outside = tmp_path / "outside"
    outside.write_text("keep")
    sock = None
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "regular":
        path.write_text("keep")
    elif kind == "fifo":
        os.mkfifo(path, mode=0o600)
    else:
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(path))
        path.chmod(0o666)
    try:
        inode = path.lstat().st_ino
        with pytest.raises(ValueError):
            with control.DesktopControl(tmp_path):
                pytest.fail("Unsafe control was accepted")
        with pytest.raises(ValueError):
            control.request(tmp_path)
        assert path.lstat().st_ino == inode and outside.read_text() == "keep"
    finally:
        if sock:
            sock.close()


def test_cleanup_does_not_unlink_a_replacement_file(tmp_path):
    with control.DesktopControl(tmp_path) as owner:
        owner.path.unlink()
        owner.path.write_text("replacement")
    assert owner.path.read_text() == "replacement"


def test_stale_owned_socket_is_reused_but_foreign_peer_is_refused(tmp_path, monkeypatch):
    path = tmp_path / control.CONTROL_FILE
    with socket.socket(socket.AF_UNIX) as stale:
        stale.bind(str(path))
        path.chmod(0o600)
    with control.DesktopControl(tmp_path) as owner:
        assert control.request(tmp_path) == owner.status()
        monkeypatch.setattr(control, "same_user", lambda _: False)
        with pytest.raises(ValueError, match="another OS user"):
            control.request(tmp_path, "stop", instance_id=owner.instance_id)
        assert not owner.stop_requested.is_set()
