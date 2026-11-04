"""Real owned native helper lifetime and credential cleanup, no Docker or model."""

import os
import shutil
import socket
import tempfile
from pathlib import Path

import macos_runner_link as link
import pytest


@pytest.fixture
def runtime():
    root = Path(tempfile.mkdtemp(prefix="astowner-", dir="/tmp")).resolve()
    path = root / "runner.sock"
    (root / "data").mkdir(mode=0o700)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as runner:
            runner.bind(str(path))
            path.chmod(0o600)
            runner.listen(1)
            yield root, path
    finally:
        shutil.rmtree(root)


def environment(path):
    return {
        "AI_STATION_RUNNER_SOCKET": str(path),
        "AI_STATION_DATA_HOST_PATH": str(path.parent / "data"),
        "AI_STATION_NATIVE_CONNECTION_PORT": "untrusted",
    }


@pytest.mark.parametrize("clean", [False, True])
def test_owned_generation_stops_before_optional_credential_cleanup_and_preserves_runner(runtime, clean):
    root, path = runtime
    before = path.stat().st_ino
    (root / "keep.txt").write_text("existing operator file")
    env = environment(path)
    value = link.NativeConnection(env).start()
    generation = value.root
    value.check()
    assert env["AI_STATION_NATIVE_CONNECTION_PORT"] == str(value.owner.port)
    assert Path(env["AI_STATION_NATIVE_CONNECTION_DIR"]) == generation / "credentials/client"
    assert not any("key.pem" in item for item in env.values())
    assert generation.stat().st_uid == os.geteuid() and generation.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match="cannot be started twice"):
        value.start()
    value.close(remove_credentials=clean)
    assert value.owner.process.returncode == 0 and generation.exists() is not clean
    assert path.stat().st_ino == before and (root / "keep.txt").read_text() == "existing operator file"
    value.close(remove_credentials=True)
    assert not generation.exists()


def test_dead_owned_helper_is_detected_without_restarting_or_replacing_it(runtime):
    root, path = runtime
    value = link.NativeConnection(environment(path)).start()
    original = value.owner.process
    try:
        original.terminate()
        original.wait(timeout=5)
        with pytest.raises(RuntimeError, match="exited unexpectedly"):
            value.check()
        assert value.owner.process is original
    finally:
        value.close(remove_credentials=True)
    assert path.is_socket() and not list(root.glob("connection-*"))


def test_replaced_generation_is_preserved_after_own_helper_stops(runtime):
    root, path = runtime
    value = link.NativeConnection(environment(path)).start()
    generation = value.root
    retained = root / "retained-original"
    generation.rename(retained)
    generation.mkdir(mode=0o700)
    (generation / "keep.txt").write_text("replacement")
    with pytest.raises(ValueError, match="replacement was preserved"):
        value.close(remove_credentials=True)
    assert value.owner.process.returncode == 0
    assert (generation / "keep.txt").read_text() == "replacement"
    assert (retained / "credentials/server/key.pem").is_file() and path.is_socket()


def test_shared_runtime_is_not_repaired_or_used_for_credentials(runtime):
    root, path = runtime
    root.chmod(0o755)
    with pytest.raises(ValueError, match="canonical private owned"):
        link.NativeConnection(environment(path)).start()
    assert root.stat().st_mode & 0o777 == 0o755 and not list(root.glob("connection-*"))


def test_server_credentials_are_never_created_inside_container_mounted_data(runtime):
    root, path = runtime
    env = {**environment(path), "AI_STATION_DATA_HOST_PATH": str(root)}
    with pytest.raises(ValueError, match="outside canonical mounted app data"):
        link.NativeConnection(env).start()
    assert path.is_socket() and not list(root.glob("connection-*"))


def test_missing_runner_cleans_only_its_fresh_verified_generation(runtime):
    root, path = runtime
    with pytest.raises((ValueError, RuntimeError)):
        link.NativeConnection(environment(root / "missing.sock")).start()
    assert path.is_socket() and not list(root.glob("connection-*"))


def test_failed_certificate_preparation_cleans_its_own_partial_generation(runtime, monkeypatch):
    root, path = runtime

    def fail(material):
        material.mkdir(mode=0o700)
        (material / "partial.key").write_text("neutral secret fixture")
        raise RuntimeError("Failed fixed certificate preparation")

    monkeypatch.setattr(link, "prepare_credentials", fail)
    with pytest.raises(RuntimeError, match="Failed fixed"):
        link.NativeConnection(environment(path)).start()
    assert path.is_socket() and not list(root.glob("connection-*"))
