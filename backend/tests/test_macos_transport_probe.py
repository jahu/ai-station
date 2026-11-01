"""Hardware-free protocol/policy checks; optional real Linux control is not Mac QA."""

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import macos_transport_probe as probe
import pytest


@pytest.fixture
def short_root():
    root = Path(tempfile.mkdtemp(prefix="ast-test-", dir="/tmp"))
    try:
        yield root
    finally:
        if not (root / "retain-for-inspection").exists():
            shutil.rmtree(root)


class LocalClient:
    """Same fixed client in a separate Python process, without Docker or a Mac claim."""

    def __init__(self):
        self.children = []
        self.tokens = []

    def container(self, sockets, data, phase):
        self.tokens.append(json.loads((sockets / "token.json").read_text()))
        child = subprocess.Popen(
            [
                sys.executable,
                "-IBS",
                "-c",
                probe.CLIENT,
                str(sockets / "channel.sock"),
                str(data),
                str(sockets / "token.json"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.children.append(child)
        return str(len(self.children))

    def call(self, *args, **kwargs):
        assert args[:2] == ("container", "wait")
        code = self.children[int(args[2]) - 1].wait(timeout=10)
        return 0, str(code)

    def close(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)


def test_separate_client_round_trip_real_wal_lock_and_restart(short_root):
    client = LocalClient()
    try:
        result = probe.experiment(client, short_root)
        assert result["socket_rebind"] and result["client_restart"]
        assert result["sqlite_wal"] and result["concurrent_writer_lock"]
        assert len(client.children) == 2 and all(child.returncode == 0 for child in client.children)
        assert client.tokens[0]["nonce"] != client.tokens[1]["nonce"]
        assert client.tokens[0]["stored"] == client.tokens[1]["stored"]
        assert not (short_root / "sockets/channel.sock").exists()
    finally:
        client.close()


def test_other_native_peer_never_reaches_file_exchange(short_root, monkeypatch):
    monkeypatch.setattr(probe, "same_user", lambda _: False)
    client = LocalClient()
    try:
        with pytest.raises(ValueError, match="native peer user"):
            probe.experiment(client, short_root)
        assert not list(short_root.rglob("artifact.bin"))
    finally:
        client.close()


@pytest.mark.parametrize("raw", [b"{}", b"x" * 257, b"[]\n", b'{"nonce":"wrong","stage":"connected"}\n'])
def test_bad_or_unframed_packets_cannot_advance_protocol(raw):
    with pytest.raises(ValueError):
        probe.packet(None, io.BytesIO(raw), "a" * 64, "connected")


def test_unlocked_copy_is_not_a_valid_shared_wal_database(tmp_path):
    nonce = "a" * 64
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(bytes.fromhex(nonce))
    artifact.chmod(0o600)
    database = tmp_path / "probe.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE probe(value TEXT NOT NULL)")
    database.chmod(0o600)
    with pytest.raises(ValueError, match="not locked"):
        probe.file_checks(tmp_path, nonce, locked=True)


def test_artifact_symlink_is_not_followed(tmp_path):
    outside = tmp_path / "keep"
    outside.write_bytes(b"preserve")
    (tmp_path / "artifact.bin").symlink_to(outside)
    with pytest.raises(ValueError, match="private regular"):
        probe.file_checks(tmp_path, "a" * 64, locked=False)
    assert outside.read_bytes() == b"preserve"


@pytest.fixture
def docker(tmp_path):
    value = probe.Docker("/fixed/docker", "unix:///private/desktop.sock", tmp_path, "amd64")
    value.image_id = probe.IMAGE_IDS["amd64"]
    return value


def state(docker, *, label=None):
    return {
        "id": "a" * 64,
        "image": probe.IMAGE_IDS["amd64"],
        "label": label or docker.identity,
        "user": f"{os.geteuid()}:{os.getegid()}",
        "running": False,
        "network": "none",
        "readonly": True,
        "memory": probe.MEMORY,
        "swap": probe.MEMORY,
        "privileged": False,
    }


def test_container_policy_and_scoped_cleanup_have_no_arbitrary_host_access(docker, tmp_path):
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("container", "inspect"):
            return 0, json.dumps(state(docker))
        return 0, "a" * 64

    docker.call = call
    docker.container(tmp_path / "sockets", tmp_path / "data", "write")
    created = calls[0]
    assert created[:2] == ("container", "create")
    assert created[created.index("--network") + 1] == "none"
    assert created[created.index("--cap-drop") + 1] == "ALL"
    assert "--read-only" in created and "no-new-privileges" in created
    assert not any("docker.sock" in value or value in {"--privileged", "--gpus"} for value in created)
    assert created[created.index("--memory") + 1] == str(probe.MEMORY)
    assert created[created.index("--pull") + 1] == "never" and probe.IMAGE in created
    assert set(docker.env) == {"PATH", "LANG"}
    assert json.loads(Path(docker.argv[-1], "config.json").read_text()) == {}
    assert docker.cleanup()
    assert calls[-1] == ("container", "rm", "a" * 64)


def test_changed_owner_is_preserved_without_stop_or_remove(docker):
    docker.ids.append("a" * 64)
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        return 0, json.dumps(state(docker, label="another-owner"))

    docker.call = call
    assert not docker.cleanup()
    assert len(calls) == 1 and calls[0][:2] == ("container", "inspect")


def test_lost_create_acknowledgement_is_not_replayed_or_reported_clean(docker, tmp_path):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired("fixed probe create", 30)

    docker.call = timeout
    with pytest.raises(subprocess.TimeoutExpired):
        docker.container(tmp_path, tmp_path, "write")
    assert docker.uncertain and len(docker.reserved_names) == 1
    assert not docker.cleanup() and len(calls) == 1


def test_no_implicit_fixture_download(docker):
    calls = []

    def missing(*args, **kwargs):
        calls.append(args)
        return 1, ""

    docker.call = missing
    with pytest.raises(RuntimeError, match="prepare-image"):
        docker.image()
    assert calls == [("image", "inspect", probe.IMAGE)]


@pytest.mark.parametrize("store", ["configuration", "manifest", "index"])
def test_only_the_fixed_publisher_chain_is_accepted_across_image_stores(docker, store):
    identifiers = {
        "configuration": probe.IMAGE_IDS["amd64"],
        "manifest": probe.MANIFESTS["amd64"],
        "index": probe.IMAGE.split("@", 1)[1],
    }
    docker.call = lambda *a, **k: (
        0,
        json.dumps([{"Id": identifiers[store], "Os": "linux", "Architecture": "amd64"}]),
    )
    assert docker.image() == identifiers[store] == docker.image_id


@pytest.mark.parametrize("change", ["id", "architecture", "os"])
def test_other_fixture_bytes_or_emulated_architecture_are_not_admitted(docker, change):
    value = {"Id": probe.IMAGE_IDS["amd64"], "Os": "linux", "Architecture": "amd64"}
    if change == "id":
        value["Id"] = "sha256:" + "f" * 64
    elif change == "architecture":
        value["Architecture"] = "arm64"
    else:
        value["Os"] = "windows"
    docker.call = lambda *a, **k: (0, json.dumps([value]))
    with pytest.raises(ValueError, match="reviewed native architecture"):
        docker.image()


def test_tcp_endpoint_is_denied_before_any_container_or_proof_write(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(probe.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(probe.shutil, "which", lambda _: "/docker")
    calls = []

    def context(*args, **kwargs):
        calls.append(args)
        return 0, "tcp://elsewhere:2375"

    monkeypatch.setattr(probe, "command", context)
    with pytest.raises(ValueError, match="local Docker Desktop Unix"):
        probe.probe(tmp_path / "proof")
    assert len(calls) == 1 and not (tmp_path / "proof").exists()


@pytest.mark.parametrize("complete", [True, False])
def test_fresh_proof_preserves_uncertain_resources_and_never_claims_installer_readiness(
    tmp_path, monkeypatch, complete
):
    monkeypatch.setattr(probe.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(probe.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(probe.shutil, "which", lambda _: "/fixed/docker")
    monkeypatch.setattr(probe, "command", lambda *a, **k: (0, "unix:///private/desktop.sock"))
    captured = {}

    class Fixture:
        identity = "fixed-test-identity"
        reserved_names = ["owned-probe-write"]
        ids = []

        def __init__(self, binary, endpoint, root, architecture):
            captured["root"] = root

        def call(self, *args, **kwargs):
            return 0, json.dumps({"system": "Docker Desktop", "os": "linux", "arch": "aarch64"})

        def image(self, **kwargs):
            return probe.IMAGE_IDS["arm64"]

        def cleanup(self):
            return complete

    monkeypatch.setattr(probe, "Docker", Fixture)
    monkeypatch.setattr(probe, "experiment", lambda *a: {"synthetic_unit_case": True})
    output = tmp_path / "fresh"
    try:
        result = probe.probe(output)
        assert result["transport_passed"] is complete
        assert result["macos_installer_qualified"] is False and result["other_os_user_tested"] is False
        assert (output / "result.json").stat().st_mode & 0o777 == 0o600
        assert json.loads((output / "result.json").read_text()) == result
        assert (output / "pending.json").exists() is (not complete)
        assert captured["root"].exists() is (not complete)
        with pytest.raises(FileExistsError):
            probe.probe(output)
    finally:
        if captured["root"].exists():
            shutil.rmtree(captured["root"])


def test_non_mac_entry_refuses_before_any_docker_or_proof_write(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.platform, "system", lambda: "Linux")
    monkeypatch.setattr(probe, "command", lambda *a, **k: pytest.fail("Unexpected Docker invocation"))
    with pytest.raises(ValueError, match="ordinary-user Mac"):
        probe.probe(tmp_path / "proof")
    assert not (tmp_path / "proof").exists()


@pytest.mark.skipif(
    os.getenv("AI_STATION_REAL_TRANSPORT_CONTROL_TESTS") != "1" or sys.platform != "linux",
    reason="Opt-in real Linux control, never Mac qualification",
)
def test_real_linux_docker_protocol_control(short_root):
    binary = shutil.which("docker")
    assert binary is not None
    docker = probe.Docker(binary, "unix:///var/run/docker.sock", short_root, "amd64")
    try:
        assert docker.image() in docker.accepted_images()
        result = probe.experiment(docker, short_root)
        result.update(
            scope="actual Linux control only",
            macos_installer_qualified=False,
            image_id=docker.image_id,
        )
        print(json.dumps(result, sort_keys=True))
    finally:
        if not docker.cleanup():
            (short_root / "retain-for-inspection").touch()
            pytest.fail("Owned cleanup incomplete; retained " + str(short_root))


@pytest.mark.skipif(
    os.getenv("AI_STATION_REAL_MAC_TRANSPORT_TESTS") != "1" or sys.platform != "darwin",
    reason="Opt-in actual Mac/Docker Desktop qualification",
)
def test_real_mac_docker_desktop_transport(tmp_path):
    result = probe.probe(tmp_path / "actual-mac-proof")
    assert result["transport_passed"] and result["cleanup_complete"]
    assert result["macos_installer_qualified"] is False
