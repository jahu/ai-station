import os
import socket
from pathlib import Path

import pytest
from ai_station_runner.unix_sockets import unix_address


def test_long_owned_path_binds_and_connects_without_moving_the_socket(tmp_path):
    parent = tmp_path / ("long-user-configuration-" * 4)
    parent.mkdir()
    path = parent / "model.sock"
    assert len(os.fsencode(path)) >= 108
    with socket.socket(socket.AF_UNIX) as server:
        with unix_address(path) as address:
            assert len(os.fsencode(address)) < 108
            server.bind(address)
        assert path.is_socket()
        server.listen(1)
        with socket.socket(socket.AF_UNIX) as client:
            with unix_address(path) as address:
                descriptor = int(address.split("/")[4])
                os.fstat(descriptor)
                client.connect(address)
            with pytest.raises(OSError):
                os.fstat(descriptor)
            # Both directory descriptors are closed before data transfer.
            connection, _ = server.accept()
            with connection:
                client.sendall(b"owned connection")
                assert connection.recv(1024) == b"owned connection"
                connection.sendall(b"reply")
                assert client.recv(1024) == b"reply"
    assert path.is_socket()


def test_legacy_short_address_does_not_change():
    with unix_address(Path("/tmp/private/model.sock")) as address:
        assert address == "/tmp/private/model.sock"


def test_directory_descriptor_is_closed_when_a_connection_fails(tmp_path):
    parent = tmp_path / ("private-owned-path-" * 5)
    parent.mkdir()
    with pytest.raises(RuntimeError):
        with unix_address(parent / "runner.sock") as address:
            descriptor = int(address.split("/")[4])
            raise RuntimeError("connection canceled")
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_long_parent_symlink_is_not_followed(tmp_path):
    target = tmp_path / "external"
    target.mkdir()
    parent = tmp_path / ("unsafe-socket-parent-" * 5)
    parent.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError):
        with unix_address(parent / "runner.sock"):
            pytest.fail("Cannot connect through an unvalidated parent symlink")
    assert list(target.iterdir()) == []
