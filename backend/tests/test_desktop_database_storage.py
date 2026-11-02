"""Persistent storage fencing and lost acknowledgements without a real Docker daemon."""

import copy
import csv
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import macos_database_storage as storage
import pytest
from app import desktop_storage as helper
from desktop_engine import DockerEngine
from test_desktop_versions import PACKAGE, installation  # noqa: F401

PACKAGE = PACKAGE | {"architecture": "x86_64"}


class Daemon:
    def __init__(self):
        self.id = "fixture-local-engine"
        self.volumes, self.containers, self.calls = {}, {}, []
        self.lose = None
        self.mutate = lambda value: None
        self.foreign = False
        self.exit = 0
        self.output = lambda value: value
        self.hang_export = False
        self.export_reports = {}

    def __call__(self, argv, **kwargs):
        assert argv[:4] == ["/fixed/docker", "--host", "unix:///fixed.sock", "--config"]
        assert kwargs["env"] == {"PATH": "/fixed" + os.pathsep + os.defpath, "LANG": "C"}
        args = argv[5:]
        self.calls.append(args)
        pair = tuple(args[:2])

        def flag(name):
            return args[args.index(name) + 1]

        def labels():
            return dict(args[i + 1].split("=", 1) for i, x in enumerate(args) if x == "--label")

        if args[0] == "info":
            return 0, json.dumps(self.id)
        if pair == ("volume", "create"):
            name = args[-1]
            self.volumes.setdefault(
                name,
                {
                    "Name": name,
                    "Driver": "local",
                    "Scope": "local",
                    "Options": None,
                    "Labels": labels(),
                    "CreatedAt": "2026-11-02T10:00:00Z",
                    "Mountpoint": "/var/lib/docker/volumes/" + name + "/_data",
                },
            )
            value = name
        elif pair == ("volume", "inspect"):
            if args[-1] not in self.volumes:
                raise ValueError("fixture volume missing")
            return 0, json.dumps([self.volumes[args[-1]]])
        elif pair == ("image", "inspect"):
            return 0, json.dumps([{"Id": args[-1], "Os": "linux", "Architecture": "amd64"}])
        elif pair == ("container", "create"):
            name = flag("--name")
            identifier = uuid4().hex * 2
            image = args.index(PACKAGE["image_id"])
            mount = dict(x.split("=", 1) if "=" in x else (x, True) for x in flag("--mount").split(","))
            volume = self.volumes[mount["source"]]
            self.containers[identifier] = {
                "Id": identifier,
                "Name": "/" + name,
                "Image": PACKAGE["image_id"],
                "Config": {
                    "Image": PACKAGE["image_id"],
                    "User": flag("--user"),
                    "Entrypoint": ["python"],
                    "Cmd": args[image + 1 :],
                    "Labels": labels(),
                },
                "HostConfig": {
                    "NetworkMode": "none",
                    "Privileged": False,
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "CapAdd": ["CAP_CHOWN"] if "--cap-add" in args else None,
                    "SecurityOpt": ["no-new-privileges"],
                    "AutoRemove": False,
                    "RestartPolicy": {"Name": "no"},
                    "Memory": int(flag("--memory")),
                    "MemorySwap": int(flag("--memory-swap")),
                    "PidsLimit": 16,
                    "NanoCpus": 1_000_000_000,
                    "PidMode": "",
                    "IpcMode": "private",
                    "Devices": [],
                    "DeviceRequests": [],
                    "PortBindings": {},
                    "Binds": None,
                    "Tmpfs": {},
                },
                "Mounts": [
                    {
                        "Type": "volume",
                        "Name": volume["Name"],
                        "Source": volume["Mountpoint"],
                        "Destination": "/database",
                        "RW": "readonly" not in mount,
                    }
                ],
                "State": {"Status": "created", "Running": False, "ExitCode": 0, "OOMKilled": False},
            }
            for i, arg in enumerate(args):
                if arg == "--mount" and i != args.index("--mount"):
                    fields = dict(
                        v.split("=", 1) if "=" in v else (v, True) for v in next(csv.reader([args[i + 1]]))
                    )
                    self.containers[identifier]["Mounts"].append(
                        {
                            "Type": "bind",
                            "Source": fields["source"],
                            "Destination": fields["target"],
                            "RW": "readonly" not in fields,
                        }
                    )
            value = identifier
        elif pair == ("container", "inspect"):
            found = next((v for v in self.containers.values() if args[-1] in (v["Id"], v["Name"][1:])), None)
            if found is None:
                raise ValueError("fixture helper missing")
            found = copy.deepcopy(found)
            self.mutate(found)
            return 0, json.dumps([found])
        elif pair == ("container", "ls"):
            condition = args[-1]
            if condition.startswith("id="):
                return 0, condition[3:] if condition[3:] in self.containers else ""
            return 0, "\n".join([*self.containers, *(["f" * 64] if self.foreign else [])])
        elif pair == ("container", "start"):
            row = self.containers[args[-1]]
            exporting = "export" in row["Config"]["Cmd"]
            if exporting and self.hang_export:
                row["State"].update(Status="running", Running=True)
            else:
                row["State"].update(Status="exited", ExitCode=self.exit)
                if exporting and self.exit == 0:
                    self.make_export(row)
            value = args[-1]
        elif pair == ("container", "stop"):
            self.containers[args[-1]]["State"].update(Status="exited", Running=False, ExitCode=143)
            value = args[-1]
        elif pair == ("container", "logs"):
            if args[-1] in self.export_reports:
                return 0, json.dumps(self.output(self.export_reports[args[-1]]))
            args = self.containers[args[-1]]["Config"]["Cmd"]
            value = helper.binding(
                flag("--storage-id"), flag("--namespace"), int(flag("--uid")), int(flag("--gid"))
            )
            if "fingerprint" in args:
                value = {"storage": value, "database": {"main": "e" * 64, "-wal": None, "-journal": None}}
            elif "empty" in args:
                value = {"storage": value, "empty": True}
            return 0, json.dumps(self.output(value))
        elif pair == ("container", "rm"):
            del self.containers[args[-1]]
            value = args[-1]
        else:
            raise AssertionError(args)
        if self.lose == pair:
            self.lose = None
            raise RuntimeError("fixture lost acknowledgement")
        return 0, value

    def make_export(self, row):
        args = row["Config"]["Cmd"]

        def flag(name):
            return args[args.index(name) + 1]

        folder = Path(next(m["Source"] for m in row["Mounts"] if m["Destination"] == "/export"))
        # Neutral trusted-image reply: native code hashes bytes but never opens SQLite.
        database = folder / "database.sqlite"
        database.write_bytes(b"neutral synthetic database export bytes")
        database.chmod(0o600)
        report = {
            "schema": 1,
            "operation_id": flag("--operation-id"),
            "image_id": flag("--image-id"),
            "storage": helper.binding(
                flag("--storage-id"), flag("--namespace"), int(flag("--uid")), int(flag("--gid"))
            ),
            "source": {"main": "e" * 64, "-wal": None, "-journal": None},
            "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "database_bytes": database.stat().st_size,
            "database_revision": "0042",
        }
        storage.write(folder / "receipt.json", report)
        self.export_reports[row["Id"]] = report


@pytest.fixture
def factory(installation, monkeypatch):  # noqa: F811
    root, config, data = installation
    daemon = Daemon()
    monkeypatch.setattr(storage, "command", daemon)
    engine = DockerEngine(
        ("/fixed/docker", "--host", "unix:///fixed.sock"), {}, ("/fixed/docker", "unix:///fixed.sock")
    )

    def create():
        return storage.DatabaseStorage(root, config, engine, PACKAGE)

    return create, daemon, root, data


def test_restart_reuses_same_persistent_volume_without_reinitializing(factory):
    create, d, root, data = factory
    owner = create()
    name = owner.prepare()
    identity = owner.identity()
    assert not d.containers and len(d.volumes) == 1
    assert (data / "db").stat().st_uid == os.geteuid()
    assert (data / "db").stat().st_mode & 0o777 == 0o700 and not list((data / "db").iterdir())
    restored = create()
    assert restored.prepare() == name and restored.identity() == identity
    assert sum(args[:2] == ["volume", "create"] for args in d.calls) == 1
    assert sum(args[:2] == ["container", "create"] and "initialize" in args for args in d.calls) == 1
    assert (root / "database-storage" / storage.RECEIPT).stat().st_mode & 0o777 == 0o600
    assert not any(args[:2] in (["volume", "rm"], ["container", "stop"]) for args in d.calls)


def test_stale_host_database_is_not_ignored_after_volume_was_prepared(factory):
    create, d, _, data = factory
    owner = create()
    owner.prepare()
    (data / "db/ai-station.sqlite").write_bytes(b"stale host database")
    before = len(d.calls)
    with pytest.raises(ValueError, match="mountpoint must remain empty"):
        create().prepare()
    assert (data / "db/ai-station.sqlite").read_bytes() == b"stale host database"
    assert not any(args[:2] == ["container", "create"] for args in d.calls[before:])


@pytest.mark.parametrize(
    "pair", [("volume", "create"), ("container", "create"), ("container", "start"), ("container", "rm")]
)
def test_completed_lost_ack_is_inspected_without_repeating_initialization(factory, pair):
    create, d, _, _ = factory
    owner = create()
    d.lose = pair
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        owner.prepare()
    owner = create()
    if pair == ("volume", "create"):
        with pytest.raises(ValueError, match="creation acknowledgement is pending"):
            owner.prepare()
        owner.recover_creation()
    owner.prepare()
    assert owner.record["phase"] == "ready" and not d.containers and len(d.volumes) == 1
    assert sum(args[:2] == ["container", "create"] and "initialize" in args for args in d.calls) == 1


@pytest.mark.parametrize("pair", [("container", "create"), ("container", "start"), ("container", "rm")])
def test_ready_inspection_lost_ack_recovers_without_reinitialization(factory, pair):
    create, d, _, _ = factory
    name = create().prepare()
    d.lose = pair
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        create().prepare()
    assert create().prepare() == name and not d.containers
    assert sum(args[:2] == ["container", "create"] and "initialize" in args for args in d.calls) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("Driver", "nfs"),
        ("CreatedAt", "different"),
        ("Options", {"device": "/elsewhere"}),
        ("Mountpoint", "/different"),
        ("Labels", {}),
    ],
)
def test_replaced_or_foreign_volume_is_preserved_without_commands(factory, key, value):
    create, d, _, _ = factory
    owner = create()
    name = owner.prepare()
    d.volumes[name][key] = value
    before = len(d.calls)
    with pytest.raises(ValueError):
        create().prepare()
    assert name in d.volumes and not d.containers
    assert not any(
        args[:2] in (["volume", "create"], ["container", "create"], ["volume", "rm"])
        for args in d.calls[before:]
    )


def test_missing_recorded_volume_is_never_recreated(factory):
    create, d, _, _ = factory
    name = create().prepare()
    del d.volumes[name]
    before = len(d.calls)
    with pytest.raises(ValueError, match="missing"):
        create().prepare()
    assert not d.volumes and not any(args[:2] == ["volume", "create"] for args in d.calls[before:])


def test_daemon_replacement_and_old_host_database_are_not_adopted(factory):
    create, d, _, data = factory
    (data / "db").mkdir()
    (data / "db/ai-station.sqlite").write_bytes(b"existing bytes")
    with pytest.raises(ValueError, match="explicit import"):
        create()
    assert (data / "db/ai-station.sqlite").read_bytes() == b"existing bytes" and not d.volumes
    (data / "db/ai-station.sqlite").unlink()
    owner = create()
    owner.prepare()
    d.id = "different-engine"
    with pytest.raises(ValueError, match="binding changed"):
        create()


def test_failed_initializer_is_not_reexecuted_or_removed(factory):
    create, d, _, _ = factory
    d.exit = 1
    with pytest.raises(ValueError, match="helper failed"):
        create().prepare()
    before = len(d.calls)
    with pytest.raises(ValueError, match="helper failed"):
        create().prepare()
    assert len(d.volumes) == len(d.containers) == 1
    assert not any(
        args[:2] in (["container", "create"], ["container", "start"], ["container", "rm"])
        for args in d.calls[before:]
    )


def test_foreign_container_prevents_root_initialization_without_stopping_it(factory):
    create, d, _, _ = factory
    d.foreign = True
    with pytest.raises(ValueError, match="Another container"):
        create().prepare()
    assert not any(args[:2] == ["container", "start"] for args in d.calls)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("Config", "User", "1000:1000"),
        ("Config", "Cmd", ["arbitrary"]),
        ("HostConfig", "PortBindings", {"8765/tcp": [{"HostPort": "8765"}]}),
    ],
)
def test_changed_helper_isolation_refuses_start_and_cleanup(factory, section, key, value):
    create, d, _, _ = factory
    d.mutate = lambda row: row[section].update({key: value})
    with pytest.raises(ValueError, match="isolation changed"):
        create().prepare()
    assert len(d.volumes) == len(d.containers) == 1
    assert not any(args[:2] in (["container", "start"], ["container", "rm"]) for args in d.calls)


def test_ordinary_user_cannot_initialize_or_forge_a_root_ownership_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "ROOT", tmp_path)
    value = helper.binding("a" * 32, "b" * 64, os.geteuid(), os.getegid())
    (tmp_path / "keep.sqlite").write_bytes(b"private existing bytes")
    with pytest.raises(ValueError, match="isolated empty-volume"):
        helper.initialize(value)
    tmp_path.chmod(0o700)
    marker = tmp_path / helper.MARKER
    marker.write_bytes(helper.encoded(value))
    marker.chmod(0o444)
    with pytest.raises(ValueError, match="marker changed"):
        helper.inspect(value)
    assert (tmp_path / "keep.sqlite").read_bytes() == b"private existing bytes"


def test_readonly_fingerprint_preserves_storage_identity_and_never_reinitializes(factory):
    create, d, _, _ = factory
    owner = create()
    owner.prepare()
    identity = owner.identity()
    assert owner.fingerprint() == {"main": "e" * 64, "-wal": None, "-journal": None}
    assert create().identity() == identity and not d.containers
    creations = [args for args in d.calls if args[:2] == ["container", "create"] and "fingerprint" in args]
    assert len(creations) == 1 and "readonly" in creations[0][creations[0].index("--mount") + 1]
    assert "--cap-add" not in creations[0]


def test_foreign_reference_refuses_fingerprint_before_dispatch_and_preserves_it(factory):
    create, d, _, _ = factory
    owner = create()
    owner.prepare()
    d.foreign = True
    before = len(d.calls)
    with pytest.raises(ValueError, match="Another container"):
        owner.fingerprint()
    assert not any(args[:2] in (["container", "create"], ["container", "stop"]) for args in d.calls[before:])


@pytest.mark.parametrize("pair", [("container", "create"), ("container", "start"), ("container", "rm")])
def test_readonly_fingerprint_lost_ack_resumes_without_write_replay(factory, pair):
    create, d, _, _ = factory
    create().prepare()
    d.lose = pair
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        create().fingerprint()
    assert create().fingerprint()["main"] == "e" * 64 and not d.containers
    assert sum(args[:2] == ["container", "create"] and "initialize" in args for args in d.calls) == 1


@pytest.mark.parametrize("change", ["wrong_storage", "missing_hash", "invalid_hash", "unfinished_journal"])
def test_fingerprint_never_accepts_incorrect_binding_or_hash_shape(factory, change):
    create, d, _, _ = factory
    owner = create()
    owner.prepare()

    def changed(value):
        if change == "wrong_storage":
            value["storage"]["storage_id"] = "f" * 32
        elif change == "missing_hash":
            del value["database"]["main"]
        elif change == "invalid_hash":
            value["database"]["main"] = "not a digest"
        else:
            value["database"]["-journal"] = "f" * 64
        return value

    d.output = changed
    with pytest.raises(ValueError, match="fingerprint acknowledgement"):
        owner.fingerprint()
    assert owner.record["command"] is not None and len(d.volumes) == 1


def test_storage_namespace_preserves_legacy_then_binds_the_ready_volume(factory):
    import desktop_versions as versions

    create, d, root, _ = factory
    owner = create()
    config = owner.config
    legacy = versions.base_namespace(config)
    with pytest.raises(ValueError, match="not ready"):
        versions.namespace(config)
    owner.prepare()
    bound = versions.namespace(config)
    assert bound[0] == legacy[0] and bound[1] != legacy[1]
    assert storage.reference(root, legacy[1]) == owner.identity()
    # Read-only operation journals never relocate an installation.
    d.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        owner.fingerprint()
    assert versions.namespace(config) == bound
    assert create().fingerprint()["main"] == "e" * 64
    assert versions.namespace(config) == bound


@pytest.mark.parametrize(
    "field", ["daemon", "architecture", "volume", "storage_id", "uid", "namespace", "missing"]
)
def test_changed_private_storage_cannot_adopt_an_existing_version(factory, field):
    import desktop_versions as versions
    from test_desktop_versions import OWNER

    create, _, root, _ = factory
    owner = create()
    owner.prepare()
    versions.begin(root, PACKAGE, owner.config, OWNER, storage=owner)
    before = (root / versions.RECEIPT).read_bytes()
    value = json.loads(owner.path.read_text())
    if field == "daemon":
        value["engine"][-1] = "other-daemon"
    elif field == "architecture":
        value["architecture"] = "arm64"
    elif field == "volume":
        value["volume"]["CreatedAt"] = "replacement-created"
    elif field == "storage_id":
        value["storage_id"] = "f" * 32
        value["name"] = value["volume"]["Name"] = "ai-station-database-" + "f" * 32
    elif field == "uid":
        value["uid"] += 1
    elif field == "namespace":
        value["namespace_sha256"] = "f" * 64
    else:
        owner.path.unlink()
    if field != "missing":
        storage.write(owner.path, value)
    with pytest.raises(ValueError):
        versions.begin(root, PACKAGE, owner.config, OWNER)
    assert (root / versions.RECEIPT).read_bytes() == before


def test_first_volume_version_requires_fixed_empty_proof_then_restart_keeps_identity(factory):
    import desktop_versions as versions
    from test_desktop_versions import OWNER

    create, d, root, _ = factory
    owner = create()
    owner.prepare()
    with pytest.raises(ValueError, match="empty-database check"):
        versions.begin(root, PACKAGE, owner.config, OWNER)
    assert not (root / versions.RECEIPT).exists()
    versions.begin(root, PACKAGE, owner.config, OWNER, storage=owner)
    value = versions.ready(root, PACKAGE, owner.config, OWNER)
    count = len(d.calls)
    restarted = versions.begin(root, PACKAGE, owner.config, "d" * 32)
    assert restarted["namespace_sha256"] == value["namespace_sha256"]
    assert len(d.calls) == count  # Namespace reads have no Docker/SQLite authority.


@pytest.mark.parametrize("pair", [("container", "create"), ("container", "start"), ("container", "rm")])
def test_first_version_lost_empty_ack_keeps_no_receipt_and_resumes_without_initializing(factory, pair):
    import desktop_versions as versions
    from test_desktop_versions import OWNER

    create, d, root, _ = factory
    owner = create()
    owner.prepare()
    d.lose = pair
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        versions.begin(root, PACKAGE, owner.config, OWNER, storage=owner)
    assert not (root / versions.RECEIPT).exists()
    resumed = create()
    versions.begin(root, PACKAGE, resumed.config, OWNER, storage=resumed)
    assert versions.load(root)["phase"] == "starting" and not d.containers
    assert sum(args[:2] == ["container", "create"] and "initialize" in args for args in d.calls) == 1


def test_nonempty_volume_cannot_be_adopted_without_a_version_receipt(factory):
    import desktop_versions as versions
    from test_desktop_versions import OWNER

    create, d, root, _ = factory
    owner = create()
    owner.prepare()
    d.exit = 1  # Fixed image refused existing database/sidecar/unknown bytes.
    with pytest.raises(ValueError, match="helper failed"):
        versions.begin(root, PACKAGE, owner.config, OWNER, storage=owner)
    assert not (root / versions.RECEIPT).exists() and len(d.volumes) == 1


@pytest.mark.parametrize("value", [False, 1, None])
def test_first_version_rejects_inexact_empty_proof(factory, value):
    import desktop_versions as versions
    from test_desktop_versions import OWNER

    create, d, root, _ = factory
    owner = create()
    owner.prepare()
    d.output = lambda v: {**v, "empty": value}
    with pytest.raises(ValueError, match="empty-database acknowledgement"):
        versions.begin(root, PACKAGE, owner.config, OWNER, storage=owner)
    assert not (root / versions.RECEIPT).exists()


def test_first_version_refuses_foreign_volume_user_without_stopping_it(factory):
    import desktop_versions as versions
    from test_desktop_versions import OWNER

    create, d, root, _ = factory
    owner = create()
    owner.prepare()
    d.foreign = True
    before = len(d.calls)
    with pytest.raises(ValueError, match="Another container"):
        versions.begin(root, PACKAGE, owner.config, OWNER, storage=owner)
    assert not (root / versions.RECEIPT).exists()
    assert not any(args[:2] in (["container", "create"], ["container", "stop"]) for args in d.calls[before:])


@pytest.fixture
def child_installation(factory, monkeypatch):
    import desktop_versions as versions
    import launch
    from test_desktop_package import fixture_bundle
    from test_desktop_versions import OWNER

    create, daemon, root, data = factory
    owner = create()
    owner.prepare()
    versions.begin(root, PACKAGE, owner.config, OWNER, storage=owner)
    bundle = root / "installed-package"
    package = fixture_bundle(bundle)
    package.update(version=PACKAGE["version"], source_epoch=PACKAGE["source_epoch"], architecture="x86_64")
    (bundle / "desktop-manifest.json").write_text(json.dumps(package))
    monkeypatch.setattr(launch, "ROOT", bundle)
    engine = DockerEngine(
        ("/fixed/docker", "--host", "unix:///fixed.sock"), {}, ("/fixed/docker", "unix:///fixed.sock")
    )
    env = {
        "AI_STATION_DATA_HOST_PATH": str(data),
        "AI_STATION_APP_IMAGE": package["image_tag"],
        "AI_STATION_NATIVE_DATABASE_VOLUME": "ambient-foreign-volume",
    }
    return owner, daemon, root, bundle, engine, env


def test_packaged_child_rechecks_binding_and_overwrites_ambient_volume_only_after_attestation(
    child_installation,
):
    import launch

    owner, daemon, _, _, engine, env = child_installation
    before = len(daemon.calls)
    launch.attest_native_database(owner.config, engine, env)
    assert env["AI_STATION_NATIVE_DATABASE_VOLUME"] == owner.record["name"]
    assert env["AI_STATION_APP_IMAGE"] == PACKAGE["image_id"]
    assert not any(args[:2] == ["volume", "create"] or "initialize" in args for args in daemon.calls[before:])


@pytest.mark.parametrize(
    "change",
    [
        "no_config",
        "missing_receipt",
        "partial",
        "tampered_package",
        "wrong_data",
        "wrong_image",
        "ready_version",
        "wrong_namespace",
        "changed_daemon",
        "foreign_reference",
        "marker",
    ],
)
def test_packaged_child_refuses_changed_or_unprepared_storage_before_compose(child_installation, change):
    import desktop_versions as versions
    import launch
    from test_desktop_versions import OWNER

    owner, daemon, root, bundle, engine, env = child_installation
    config = owner.config
    if change == "no_config":
        config = None
    elif change == "missing_receipt":
        owner.path.unlink()
    elif change == "partial":
        storage.write(owner.path, owner.record | {"phase": "initialized"})
    elif change == "tampered_package":
        (bundle / "station").write_text("changed package bytes")
    elif change == "wrong_data":
        env["AI_STATION_DATA_HOST_PATH"] = str(root / "other-data")
    elif change == "wrong_image":
        env["AI_STATION_APP_IMAGE"] = "another-package:latest"
    elif change == "ready_version":
        versions.ready(root, PACKAGE, owner.config, OWNER)
    elif change == "wrong_namespace":
        versions.save(root, versions.load(root) | {"namespace_sha256": "f" * 64})
    elif change == "changed_daemon":
        daemon.id = "replacement-daemon"
    elif change == "foreign_reference":
        daemon.foreign = True
    else:
        daemon.output = lambda v: {**v, "storage_id": "f" * 32}
    before = len(daemon.calls)
    with pytest.raises((ValueError, RuntimeError)):
        launch.attest_native_database(config, engine, env)
    assert env["AI_STATION_NATIVE_DATABASE_VOLUME"] == "ambient-foreign-volume"
    assert not any(
        args[:1] == ["compose"] or args[:2] in (["volume", "create"], ["container", "stop"])
        for args in daemon.calls[before:]
    )


def test_database_export_uses_readonly_volume_and_private_native_output_without_replay(factory):
    create, d, root, data = factory
    owner = create()
    owner.prepare()
    operation = str(uuid4())
    report = owner.export_database(operation)
    folder = root / "database-exports" / operation
    assert not folder.is_relative_to(data) and report["database_revision"] == "0042"
    stamp = (folder / "database.sqlite").stat().st_mtime_ns
    before = len(d.calls)
    assert create().export_database(operation) == report
    assert (folder / "database.sqlite").stat().st_mtime_ns == stamp
    assert not any(args[:2] == ["container", "create"] for args in d.calls[before:])
    assert len(d.volumes) == 1 and not d.containers


@pytest.mark.parametrize("pair", [("container", "create"), ("container", "start"), ("container", "rm")])
def test_export_lost_ack_recovers_same_helper_and_never_rewrites_snapshot(factory, pair):
    create, d, _, _ = factory
    create().prepare()
    operation = str(uuid4())
    d.lose = pair
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        create().export_database(operation)
    assert create().export_database(operation)["operation_id"] == operation
    assert (
        sum(args[:2] == ["container", "create"] and "app.desktop_snapshot" in args for args in d.calls) == 1
    )
    assert not d.containers


@pytest.mark.parametrize("change", ["source", "readonly", "missing"])
def test_changed_export_mount_never_starts_helper(factory, change):
    create, d, _, _ = factory
    create().prepare()

    def mutate(row):
        if "export" not in row["Config"]["Cmd"]:
            return
        output = next(m for m in row["Mounts"] if m["Destination"] == "/export")
        if change == "missing":
            row["Mounts"].remove(output)
        elif change == "source":
            output["Source"] = "/foreign/private"
        else:
            output["RW"] = False

    d.mutate = mutate
    before = len(d.calls)
    with pytest.raises(ValueError, match="identity or isolation"):
        create().export_database(str(uuid4()))
    assert not any(args[:2] == ["container", "start"] for args in d.calls[before:])


def test_foreign_volume_reference_prevents_export_before_dispatch(factory):
    create, d, _, _ = factory
    create().prepare()
    d.foreign = True
    before = len(d.calls)
    with pytest.raises(ValueError, match="Another container"):
        create().export_database(str(uuid4()))
    assert not any(args[:2] in (["container", "create"], ["container", "stop"]) for args in d.calls[before:])


def test_export_file_tampering_cannot_return_a_completed_snapshot(factory):
    create, _, root, _ = factory
    create().prepare()
    operation = str(uuid4())
    create().export_database(operation)
    (root / "database-exports" / operation / "database.sqlite").write_bytes(b"changed exported data")
    with pytest.raises(ValueError, match="exported database bytes"):
        create().export_database(operation)


def test_cancel_only_owned_export_after_lost_start_ack_preserves_partial_bytes(factory):
    create, d, root, _ = factory
    create().prepare()
    operation = str(uuid4())
    d.hang_export = True
    d.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().export_database(operation)
    outcome = create().cancel_export(operation)
    assert outcome["status"] == "canceled" and not d.containers and len(d.volumes) == 1
    assert (root / "database-exports" / operation).is_dir()
    assert sum(args[:2] == ["container", "stop"] for args in d.calls) == 1


def test_cancel_refuses_another_export_identity_without_signaling_it(factory):
    create, d, _, _ = factory
    create().prepare()
    d.hang_export = True
    d.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().export_database(str(uuid4()))
    before = len(d.calls)
    with pytest.raises(ValueError, match="matching owned"):
        create().cancel_export(str(uuid4()))
    assert not any(args[:2] == ["container", "stop"] for args in d.calls[before:])


@pytest.mark.parametrize("pair", [("container", "stop"), ("container", "rm")])
def test_export_cancellation_lost_ack_is_reconciled_without_signaling_again(factory, pair):
    create, d, _, _ = factory
    create().prepare()
    operation = str(uuid4())
    d.hang_export = True
    d.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().export_database(operation)
    d.lose = pair
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        create().cancel_export(operation)
    assert create().cancel_export(operation)["status"] == "canceled"
    assert not d.containers
    assert sum(args[:2] == ["container", "stop"] for args in d.calls) == 1


def test_completed_export_is_preserved_when_cancel_arrives_after_success(factory):
    create, d, root, _ = factory
    create().prepare()
    operation = str(uuid4())
    d.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().export_database(operation)
    assert create().cancel_export(operation)["status"] == "completed"
    assert not any(args[:2] == ["container", "stop"] for args in d.calls)
    assert (root / "database-exports" / operation / "database.sqlite").exists()


def test_empty_export_reservation_can_resume_after_foreign_reference_is_removed(factory):
    create, d, _, _ = factory
    create().prepare()
    operation = str(uuid4())
    d.foreign = True
    with pytest.raises(ValueError):
        create().export_database(operation)
    d.foreign = False
    assert create().export_database(operation)["operation_id"] == operation


def test_canceled_export_identity_cannot_implicitly_start_another_snapshot(factory):
    create, d, _, _ = factory
    create().prepare()
    operation = str(uuid4())
    d.hang_export = True
    d.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().export_database(operation)
    create().cancel_export(operation)
    before = len(d.calls)
    with pytest.raises((ValueError, FileNotFoundError)):
        create().export_database(operation)
    assert not any(args[:2] == ["container", "create"] for args in d.calls[before:])


def test_cancel_rechecks_a_live_helper_even_if_prior_cleanup_phase_is_finished(factory):
    create, d, _, _ = factory
    create().prepare()
    operation = str(uuid4())
    d.hang_export = True
    d.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().export_database(operation)
    # A delayed start can win the created→cleanup race. A finished journal must
    # not suppress inspection/Stop while that exact owned container still exists.
    owner = create()
    owner.record["command"]["phase"] = "finished"
    owner.save()
    assert create().cancel_export(operation)["status"] == "canceled"
    assert sum(args[:2] == ["container", "stop"] for args in d.calls) == 1
    assert not d.containers
