"""Fixed image dispatch/recovery boundaries, without a daemon, GPU or user data."""

import copy
import csv
import hashlib
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import desktop_upgrade_image as upgrade
import desktop_versions as versions
import pytest
import test_desktop_versions as fixtures
from desktop_engine import DockerEngine
from launch import ensure_recovery_finished

installation = fixtures.installation
PREVIOUS = fixtures.PACKAGE
TARGET = PREVIOUS | {
    "bundle_id": "d" * 64,
    "image_id": "sha256:" + "e" * 64,
    "version": "0.2.0",
    "source_epoch": PREVIOUS["source_epoch"] + 1,
    "architecture": "x86_64",
}


class Daemon:
    """Neutral Docker replies; real CLI/isolation coverage is a separate opt-in proof."""

    def __init__(self):
        self.containers = {}
        self.calls = []
        self.starts = 0
        self.busy = False
        self.architecture = "amd64"
        self.mutate = lambda value: None
        self.lose_ack = None
        self.fail_before = None
        self.hang = False
        self.bad_output = None

    def __call__(self, argv, **kwargs):
        assert argv[:3] == ["/fixed/docker", "--host", "unix:///fixed.sock"]
        assert argv[3] == "--config"
        assert kwargs["env"] == {"PATH": "/fixed" + os.pathsep + os.defpath, "LANG": "C"}
        args = argv[5:]
        pair = tuple(args[:2])
        self.calls.append(args)
        if self.fail_before == pair:
            raise RuntimeError("The neutral daemon did not acknowledge the operation")
        if pair == ("image", "inspect"):
            return 0, json.dumps(
                [{"Id": TARGET["image_id"], "Os": "linux", "Architecture": self.architecture}]
            )
        if pair == ("container", "ls"):
            condition = args[-1]
            if condition.startswith("label="):
                return 0, "f" * 64 if self.busy else ""
            return 0, "\n".join(k for k in self.containers if k == condition.removeprefix("id="))
        if pair == ("container", "create"):

            def flag(name):
                return args[args.index(name) + 1]

            labels = {
                args[i + 1].split("=", 1)[0]: args[i + 1].split("=", 1)[1]
                for i, v in enumerate(args)
                if v == "--label"
            }
            mount = dict(value.split("=", 1) for value in next(csv.reader([flag("--mount")])))
            extra_mounts = []
            for i, arg in enumerate(args):
                if arg == "--mount" and i != args.index("--mount"):
                    fields = dict(v.split("=", 1) for v in next(csv.reader([args[i + 1]])) if "=" in v)
                    assert fields["type"] == "volume" and fields["target"] == "/data/db"
                    extra_mounts.append(
                        {
                            "Type": "volume",
                            "Name": fields["source"],
                            "Source": "/var/lib/docker/volumes/" + fields["source"] + "/_data",
                            "Destination": "/data/db",
                            "RW": True,
                            "Driver": "local",
                        }
                    )
            identifier = uuid4().hex * 2
            entry = args.index(TARGET["image_id"])
            self.containers[identifier] = {
                "Id": identifier,
                "Name": "/" + flag("--name"),
                "Image": TARGET["image_id"],
                "Config": {
                    "Image": TARGET["image_id"],
                    "User": flag("--user"),
                    "Entrypoint": [flag("--entrypoint")],
                    "Cmd": args[entry + 1 :],
                    "Labels": labels,
                },
                "HostConfig": {
                    "PidMode": "",
                    "IpcMode": "private",
                    "Tmpfs": {"/tmp": flag("--tmpfs").split(":", 1)[1]},
                    "NetworkMode": flag("--network"),
                    "Privileged": False,
                    "ReadonlyRootfs": "--read-only" in args,
                    "AutoRemove": False,
                    "RestartPolicy": {"Name": flag("--restart")},
                    "Memory": int(flag("--memory")),
                    "MemorySwap": int(flag("--memory-swap")),
                    "PidsLimit": int(flag("--pids-limit")),
                    "NanoCpus": int(flag("--cpus")) * 1_000_000_000,
                    "CapDrop": [flag("--cap-drop")],
                    "SecurityOpt": [flag("--security-opt")],
                    "Devices": [],
                    "DeviceRequests": [],
                    "PortBindings": {},
                },
                "Mounts": [
                    {"Type": "bind", "Source": mount["source"], "Destination": mount["target"], "RW": True}
                ]
                + extra_mounts,
                "State": {"Running": False, "Status": "created", "ExitCode": 0, "OOMKilled": False},
            }
            result = identifier
        elif pair == ("container", "inspect"):
            found = next(
                (v for v in self.containers.values() if args[-1] in (v["Id"], v["Name"].removeprefix("/"))),
                None,
            )
            if found is None:
                raise RuntimeError("The neutral daemon has no confirmed container")
            result = copy.deepcopy(found)
            self.mutate(result)
            return 0, json.dumps([result])
        elif pair == ("container", "start"):
            self.starts += 1
            self.containers[args[-1]]["State"].update(
                Running=self.hang, Status="running" if self.hang else "exited"
            )
            result = args[-1]
        elif pair == ("container", "logs"):
            if self.bad_output is not None:
                return 0, self.bad_output
            cfg = self.containers[args[-1]]["Config"]
            identity = cfg["Labels"]["ai-station.desktop-upgrade"]
            action = cfg["Cmd"][2]
            result = json.dumps(
                {
                    "operation_id": identity,
                    "phase": {
                        "prepare": "prepared",
                        "publish": "applied",
                        "abort": "aborted",
                        "status": "prepared",
                    }[action],
                    "schema_before": "0041",
                    "schema_after": "0042",
                    "backup_relative": f"desktop-upgrades/{identity}/original.sqlite",
                    "backup_verified": True,
                }
            )
        elif pair == ("container", "stop"):
            self.containers[args[-1]]["State"].update(Running=False, Status="exited", ExitCode=143)
            result = args[-1]
        elif pair == ("container", "rm"):
            self.containers.pop(args[-1])
            result = args[-1]
        else:
            pytest.fail("Unexpected daemon command: " + repr(args))
        if self.lose_ack == pair:
            self.lose_ack = None
            raise OSError("Simulated lost daemon acknowledgement")
        return 0, result


@pytest.fixture
def setup(installation, monkeypatch):
    root, config, data = installation
    (data / "runtime").mkdir(mode=0o700)
    versions.begin(root, PREVIOUS, config, "c" * 32)
    versions.ready(root, PREVIOUS, config, "c" * 32)
    daemon = Daemon()
    monkeypatch.setattr(upgrade, "command", daemon)
    engine = DockerEngine(
        ("/fixed/docker", "--host", "unix:///fixed.sock"), {}, ("/fixed/docker", "unix:///fixed.sock")
    )
    identity = str(uuid4())
    client = upgrade.UpgradeImage(root, config, engine, PREVIOUS, TARGET, identity)
    return SimpleNamespace(
        root=root, config=config, data=data, engine=engine, identity=identity, daemon=daemon, client=client
    )


def test_preparation_is_once_only_and_normal_startup_stays_fenced(setup):
    result = setup.client.run("prepare")
    assert result["phase"] == "prepared" and setup.daemon.starts == 1
    assert not setup.daemon.containers
    before = copy.deepcopy(setup.daemon.calls)
    assert setup.client.run("prepare") == result and setup.daemon.calls == before
    with pytest.raises(RuntimeError, match="pending offline desktop upgrade"):
        ensure_recovery_finished(setup.data / "runtime")
    assert versions.load(setup.root)["package"] == PREVIOUS


@pytest.mark.parametrize("operation", ["create", "start", "rm"])
def test_lost_ack_reconstructs_same_container_and_never_restarts_a_command(setup, operation):
    setup.daemon.lose_ack = ("container", operation)
    with pytest.raises(OSError):
        setup.client.run("prepare")
    restarted = upgrade.UpgradeImage(setup.root, setup.config, setup.engine, PREVIOUS, TARGET, setup.identity)
    assert restarted.resume()["phase"] == "prepared"
    assert setup.daemon.starts == 1 and not setup.daemon.containers
    assert len([c for c in setup.daemon.calls if c[:2] == ["container", "create"]]) == 1


@pytest.mark.parametrize("failure", ["compose", "architecture", "unknown_action", "timeout"])
def test_invalid_prerequisite_never_dispatches_or_fences_a_workload(setup, failure):
    setup.daemon.busy = failure == "compose"
    setup.daemon.architecture = "arm64" if failure == "architecture" else "amd64"
    with pytest.raises((RuntimeError, ValueError)):
        setup.client.run(
            "shell" if failure == "unknown_action" else "prepare",
            timeout=False if failure == "timeout" else 60,
        )
    assert not setup.daemon.containers and setup.daemon.starts == 0
    assert not (setup.data / "runtime" / upgrade.FENCE).exists()


@pytest.mark.parametrize(
    "field",
    [
        "user",
        "command",
        "image",
        "label",
        "mount",
        "gpu",
        "memory",
        "readonly",
        "pid_namespace",
        "ipc_namespace",
        "tmpfs",
    ],
)
def test_changed_container_identity_or_isolation_is_never_started_or_stopped(setup, field):
    def mutate(value):
        if field == "user":
            value["Config"]["User"] = "0:0"
        elif field == "command":
            value["Config"]["Cmd"] = ["-c", "anything"]
        elif field == "image":
            value["Image"] = "sha256:" + "0" * 64
        elif field == "label":
            value["Config"]["Labels"]["ai-station.desktop-upgrade"] = str(uuid4())
        elif field == "mount":
            value["Mounts"].append({"Source": "/outside", "Destination": "/outside"})
        elif field == "gpu":
            value["HostConfig"]["DeviceRequests"] = [{"Count": -1}]
        elif field == "memory":
            value["HostConfig"]["MemorySwap"] = -1
        elif field == "pid_namespace":
            value["HostConfig"]["PidMode"] = "host"
        elif field == "ipc_namespace":
            value["HostConfig"]["IpcMode"] = "host"
        elif field == "tmpfs":
            value["HostConfig"]["Tmpfs"] = {"/tmp": "rw"}
        else:
            value["HostConfig"]["ReadonlyRootfs"] = False

    setup.daemon.mutate = mutate
    with pytest.raises(ValueError, match="identity or isolation changed"):
        setup.client.run("prepare")
    assert setup.daemon.starts == 0
    assert not any(c[:2] == ["container", "stop"] for c in setup.daemon.calls)
    assert (setup.data / "runtime" / upgrade.FENCE).exists()


@pytest.mark.parametrize("operation", ["create", "start"])
def test_unknown_dispatch_is_retained_and_never_blindly_repeated(setup, operation):
    setup.daemon.fail_before = ("container", operation)
    with pytest.raises(RuntimeError):
        setup.client.run("prepare")
    setup.daemon.fail_before = None
    with pytest.raises(RuntimeError):
        setup.client.run("prepare")
    assert len([c for c in setup.daemon.calls if c[:2] == ["container", operation]]) == 1
    assert setup.daemon.starts == 0
    assert (setup.data / "runtime" / upgrade.FENCE).exists()


def test_deadline_stops_only_verified_container_then_keeps_startup_fenced(setup):
    setup.daemon.hang = True
    with pytest.raises(RuntimeError, match="timed out"):
        setup.client.run("prepare", timeout=0.01)
    assert setup.daemon.starts == 1
    with pytest.raises(RuntimeError, match="failed"):
        setup.client.resume()
    assert not setup.daemon.containers and setup.client.state()["current"] is None
    with pytest.raises(RuntimeError, match="not repeated"):
        setup.client.run("prepare")
    assert (setup.data / "runtime" / upgrade.FENCE).exists()


def test_owned_memory_failure_is_reported_without_replaying_the_migration(setup):
    def oom(value):
        if value["State"]["Status"] == "exited":
            value["State"].update(OOMKilled=True, ExitCode=137)

    setup.daemon.mutate = oom
    with pytest.raises(RuntimeError, match="offline upgrade failed"):
        setup.client.run("prepare")
    assert setup.daemon.starts == 1 and not setup.daemon.containers
    assert (setup.data / "runtime" / upgrade.FENCE).exists()
    state = setup.client.state()
    assert next(iter(state["commands"].values()))["exit_code"] == 137
    with pytest.raises(RuntimeError, match="not repeated"):
        setup.client.run("prepare")


def test_invalid_result_never_enters_private_receipts_or_activates_a_version(setup):
    setup.daemon.bad_output = json.dumps({"setup_token": "synthetic-secret-never-retained"})
    with pytest.raises(ValueError, match="invalid transaction receipt") as failure:
        setup.client.run("prepare")
    assert "synthetic-secret" not in str(failure.value)
    assert "synthetic-secret" not in (setup.client.folder / "state.json").read_text()
    with pytest.raises(RuntimeError, match="pending image command"):
        setup.client.finish(activate=True)
    assert versions.load(setup.root)["package"] == PREVIOUS


@pytest.mark.parametrize("field", ["action", "name", "container_id"])
def test_corrupt_private_command_cannot_become_cli_arguments(setup, field):
    setup.client.run("prepare")
    state = setup.client.state()
    item = next(iter(state["commands"].values()))
    item[field] = "--untrusted-option"
    upgrade.write(setup.client.folder / "state.json", state)
    before = copy.deepcopy(setup.daemon.calls)
    with pytest.raises(ValueError, match="recorded image command"):
        setup.client.run("status")
    assert setup.daemon.calls == before


def test_changed_engine_and_namespace_cannot_reuse_an_operation(setup):
    other = DockerEngine(
        ("/fixed/docker", "--host", "unix:///other.sock"), {}, ("/fixed/docker", "unix:///other.sock")
    )
    with pytest.raises(ValueError, match="different package/storage/engine"):
        upgrade.UpgradeImage(setup.root, setup.config, other, PREVIOUS, TARGET, setup.identity)
    setup.config.write_text(setup.config.read_text().replace("ai-station-test", "another-project"))
    with pytest.raises(ValueError, match="storage changed"):
        setup.client.run("prepare")
    assert not setup.daemon.containers


def staged_data(setup):
    setup.client.run("prepare")
    setup.client.run("publish")
    folder = setup.data / "desktop-upgrades" / setup.identity
    folder.mkdir(parents=True, mode=0o700)
    folder.parent.chmod(0o700)
    request = {
        "operation_id": setup.identity,
        "previous_bundle": PREVIOUS["bundle_id"],
        "target_bundle": TARGET["bundle_id"],
        "schema_before": "0041",
        "schema_after": "0042",
    }
    digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    state = {
        "phase": "applied",
        "request_identity": digest,
        "staged_sha256": hashlib.sha256(b"neutral data publication fixture").hexdigest(),
    }
    upgrade.write(folder / "request.json", request)
    upgrade.write(folder / "state.json", state)
    (setup.data / "db").mkdir(mode=0o700)
    (setup.data / "db/ai-station.sqlite").write_bytes(b"neutral data publication fixture")
    return folder


def test_activation_is_durable_before_startup_fence_is_removed_and_never_replayed(setup):
    staged_data(setup)
    result = setup.client.finish(activate=True)
    assert versions.load(setup.root)["package"] == versions.package_identity(TARGET)
    assert versions.load(setup.root)["phase"] == "starting"
    assert not (setup.data / "runtime" / upgrade.FENCE).exists()
    versions.begin(setup.root, TARGET, setup.config, "f" * 32)
    (setup.data / "db/ai-station.sqlite").write_bytes(b"later legitimate user data")
    before = versions.load(setup.root)
    calls = copy.deepcopy(setup.daemon.calls)
    assert setup.client.finish(activate=True) == result
    assert setup.client.run("publish") == result
    assert setup.daemon.calls == calls and versions.load(setup.root) == before
    assert (setup.data / "db/ai-station.sqlite").read_bytes() == b"later legitimate user data"


@pytest.mark.parametrize("field", ["request", "phase", "database", "wal", "owner", "shared_write"])
def test_changed_publication_cannot_activate_or_remove_startup_fence(setup, field):
    folder = staged_data(setup)
    if field == "request":
        value = upgrade.read_json(folder / "request.json")
        value["target_bundle"] = "0" * 64
        upgrade.write(folder / "request.json", value)
    elif field == "phase":
        value = upgrade.read_json(folder / "state.json")
        value["phase"] = "publishing"
        upgrade.write(folder / "state.json", value)
    elif field == "database":
        (setup.data / "db/ai-station.sqlite").write_bytes(b"unexpected later writes")
    elif field == "wal":
        (setup.data / "db/ai-station.sqlite-wal").write_bytes(b"unexpected WAL transaction")
    elif field == "shared_write":
        (setup.data / "db/ai-station.sqlite").chmod(0o660)
    else:
        versions.begin(setup.root, PREVIOUS, setup.config, "f" * 32)
    before = versions.load(setup.root)
    with pytest.raises(ValueError):
        setup.client.finish(activate=True)
    assert (setup.data / "runtime" / upgrade.FENCE).exists()
    assert versions.load(setup.root) == before


def test_lost_native_activation_ack_resumes_without_rewriting_version_receipt(setup, monkeypatch):
    staged_data(setup)
    original = setup.client.save

    def lose_ack(state):
        original(state)
        if state["final"] is not None:
            raise OSError("Simulated lost native activation acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(setup.client, "save", lose_ack)
        with pytest.raises(OSError):
            setup.client.finish(activate=True)
    before = versions.load(setup.root)
    assert (setup.data / "runtime" / upgrade.FENCE).exists()
    resumed = upgrade.UpgradeImage(setup.root, setup.config, setup.engine, PREVIOUS, TARGET, setup.identity)
    assert resumed.finish(activate=True)["phase"] == "applied"
    assert versions.load(setup.root) == before
    assert not (setup.data / "runtime" / upgrade.FENCE).exists()


def test_container_default_sqlite_mode_is_valid_inside_private_data_root(setup):
    staged_data(setup)
    (setup.data / "db/ai-station.sqlite").chmod(0o644)
    assert setup.client.finish(activate=True)["phase"] == "applied"


@pytest.mark.parametrize("changed", [False, True])
def test_abort_preserves_original_nonempty_wal_but_never_accepts_changed_wal(setup, changed):
    setup.client.run("prepare")
    setup.client.run("abort")
    folder = setup.data / "desktop-upgrades" / setup.identity
    folder.mkdir(mode=0o700, parents=True)
    folder.parent.chmod(0o700)
    (setup.data / "db").mkdir(mode=0o700)
    database = setup.data / "db/ai-station.sqlite"
    database.write_bytes(b"original database fixture")
    wal = database.with_name(database.name + "-wal")
    wal.write_bytes(b"original preserved WAL fixture")
    request = {
        "operation_id": setup.identity,
        "previous_bundle": PREVIOUS["bundle_id"],
        "target_bundle": TARGET["bundle_id"],
        "schema_before": "0041",
        "schema_after": "0042",
        "source": {"main": upgrade.data_digest(database), "-wal": upgrade.data_digest(wal), "-journal": None},
    }
    request_hash = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    upgrade.write(folder / "request.json", request)
    upgrade.write(folder / "state.json", {"phase": "aborted", "request_identity": request_hash})
    if changed:
        wal.write_bytes(b"unexpected later WAL writes")
        with pytest.raises(ValueError, match="sidecar writes"):
            setup.client.finish(activate=False)
        assert (setup.data / "runtime" / upgrade.FENCE).exists()
    else:
        assert setup.client.finish(activate=False)["phase"] == "aborted"
        assert not (setup.data / "runtime" / upgrade.FENCE).exists()
        assert wal.read_bytes() == b"original preserved WAL fixture"
    assert versions.load(setup.root)["package"] == PREVIOUS


@pytest.fixture
def volume_setup(setup, monkeypatch):
    import macos_database_storage as storage

    folder = setup.root / "database-storage"
    folder.mkdir(mode=0o700)
    upgrade.write(folder / storage.RECEIPT, {"synthetic": "private owner fixture"})
    (setup.data / "db").mkdir(mode=0o700)

    class Volume:
        record = {"name": "fixture-db", "volume": {"Mountpoint": "/var/lib/docker/volumes/fixture-db/_data"}}
        binding = "b" * 64
        changed = False
        foreign = False
        bad_marker = False
        verified = 0
        reads = 0
        fail_read_once = False
        observed = {
            "main": hashlib.sha256(b"neutral volume database fixture").hexdigest(),
            "-wal": None,
            "-journal": None,
        }

        def identity(self, *, allow_pending_readonly=False):
            return ("f" * 64) if self.changed else self.binding

        def owned(self):
            return self.record["volume"]

        def quiescent(self, *, allowed=()):
            assert set(allowed) == set(setup.daemon.containers), (
                "Only the fully verified owned upgrade helper may be exempt"
            )
            if self.foreign:
                raise ValueError("Foreign database container was preserved")

        def prepare(self):
            self.verified += 1
            if self.bad_marker:
                raise ValueError("Database ownership marker changed")

        def application_mount(self):
            return "type=volume,source=fixture-db,target=/data/db,volume-nocopy"

        def fingerprint(self):
            self.reads += 1
            if self.fail_read_once:
                self.fail_read_once = False
                raise OSError("Lost read-only fingerprint acknowledgement")
            return dict(self.observed)

    value = Volume()
    monkeypatch.setattr(storage, "DatabaseStorage", lambda *args: value)
    setup.identity = str(uuid4())
    setup.client = upgrade.UpgradeImage(
        setup.root, setup.config, setup.engine, PREVIOUS, TARGET, setup.identity
    )
    setup.volume = value
    return setup


def volume_publication(value):
    value.client.run("prepare")
    value.client.run("publish")
    folder = value.data / "desktop-upgrades" / value.identity
    folder.mkdir(parents=True, mode=0o700)
    folder.parent.chmod(0o700)
    request = {
        "operation_id": value.identity,
        "previous_bundle": PREVIOUS["bundle_id"],
        "target_bundle": TARGET["bundle_id"],
        "schema_before": "0041",
        "schema_after": "0042",
    }
    state = {
        "phase": "applied",
        "request_identity": hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "staged_sha256": value.volume.observed["main"],
    }
    upgrade.write(folder / "request.json", request)
    upgrade.write(folder / "state.json", state)


def test_volume_commands_mount_verified_database_and_activate_without_host_sqlite(volume_setup, monkeypatch):
    value = volume_setup
    monkeypatch.setattr(
        upgrade, "data_digest", lambda *_: pytest.fail("Native host must never hash the active volume DB")
    )
    volume_publication(value)
    assert value.client.request["database_storage"] == value.volume.binding
    assert value.volume.verified == 2 and not list((value.data / "db").iterdir())
    assert value.client.finish(activate=True)["phase"] == "applied"
    assert value.volume.reads == 1 and value.daemon.starts == 2
    assert versions.load(value.root)["package"] == versions.package_identity(TARGET)


@pytest.mark.parametrize("change", ["foreign", "binding", "marker", "missing_receipt"])
def test_volume_change_or_foreign_reference_refuses_dispatch_without_stopping_it(volume_setup, change):
    value = volume_setup
    if change == "foreign":
        value.volume.foreign = True
    elif change == "binding":
        value.volume.changed = True
    elif change == "marker":
        value.volume.bad_marker = True
    else:
        (value.root / "database-storage/database-storage.json").unlink()
    with pytest.raises(ValueError):
        value.client.run("prepare")
    assert value.daemon.starts == 0
    assert not any(c[:2] == ["container", "stop"] for c in value.daemon.calls)
    assert versions.load(value.root)["package"] == PREVIOUS


@pytest.mark.parametrize("field", ["missing", "name", "source", "readonly", "driver"])
def test_changed_volume_mount_is_never_started(volume_setup, field):
    value = volume_setup

    def changed(row):
        if field == "missing":
            row["Mounts"].pop()
        else:
            key = {"name": "Name", "source": "Source", "readonly": "RW", "driver": "Driver"}[field]
            row["Mounts"][-1][key] = False if field == "readonly" else "foreign"

    value.daemon.mutate = changed
    with pytest.raises(ValueError, match="identity or isolation"):
        value.client.run("prepare")
    assert value.daemon.starts == 0


@pytest.mark.parametrize("field", ["main", "-wal", "-journal"])
def test_changed_volume_bytes_cannot_activate_or_remove_fence(volume_setup, field):
    value = volume_setup
    volume_publication(value)
    value.volume.observed = {**value.volume.observed, field: "f" * 64}
    with pytest.raises(ValueError):
        value.client.finish(activate=True)
    assert versions.load(value.root)["package"] == PREVIOUS
    assert (value.data / "runtime" / upgrade.FENCE).exists()


def test_lost_volume_fingerprint_ack_reopens_without_replaying_publication(volume_setup):
    value = volume_setup
    volume_publication(value)
    value.volume.fail_read_once = True
    with pytest.raises(OSError, match="fingerprint acknowledgement"):
        value.client.finish(activate=True)
    resumed = upgrade.UpgradeImage(value.root, value.config, value.engine, PREVIOUS, TARGET, value.identity)
    assert resumed.finish(activate=True)["phase"] == "applied" and value.daemon.starts == 2
    assert not (value.data / "runtime" / upgrade.FENCE).exists()
