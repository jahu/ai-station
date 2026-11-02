"""Persistent storage fencing and lost acknowledgements without a real Docker daemon."""

import copy
import json
import os
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
                    "Memory": storage.MEMORY,
                    "MemorySwap": storage.MEMORY,
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
            self.containers[args[-1]]["State"].update(Status="exited", ExitCode=self.exit)
            value = args[-1]
        elif pair == ("container", "logs"):
            args = self.containers[args[-1]]["Config"]["Cmd"]
            value = helper.binding(
                flag("--storage-id"), flag("--namespace"), int(flag("--uid")), int(flag("--gid"))
            )
            if "fingerprint" in args:
                value = {"storage": value, "database": {"main": "e" * 64, "-wal": None, "-journal": None}}
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
