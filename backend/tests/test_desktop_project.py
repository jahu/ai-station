import copy
import json
import os
import subprocess
from types import SimpleNamespace

import pytest
from desktop_engine import DockerEngine
from desktop_project import RECEIPT, SERVICES, DesktopProject, container_ids


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "station"
    root.mkdir(mode=0o700)
    data = root / "data"
    data.mkdir(mode=0o700)
    source = tmp_path / "package"
    source.mkdir()
    env = {"AI_STATION_DATA_HOST_PATH": str(data), "COMPOSE_PROJECT_NAME": "ai-station-desktop-test"}
    config = root / "desktop.env"
    values = {**env, "AI_STATION_ACCESS_PROFILE": "accounts"}
    config.write_text("".join(k + "=" + json.dumps(v) + "\n" for k, v in values.items()))
    config.chmod(0o600)
    items = {}
    for number, service in enumerate(sorted(SERVICES), 1):
        identity = f"{number:064x}"
        items[identity] = {
            "Id": identity,
            "Image": "sha256:" + "a" * 64,
            "Config": {
                "Env": ["PRIVATE_TOKEN=do-not-persist-this"],
                "Labels": {
                    "com.docker.compose.project": env["COMPOSE_PROJECT_NAME"],
                    "com.docker.compose.service": service,
                    "com.docker.compose.container-number": "1",
                    "com.docker.compose.oneoff": "False",
                    "com.docker.compose.project.working_dir": str(source),
                },
            },
            "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
            "Mounts": [{"Type": "bind", "Source": str(data), "Destination": "/data"}],
            "State": {"Pid": 1234, "StartedAt": "before-reboot"},
        }
    # Same daemon, but deliberately excluded from the Compose inventory.
    unrelated = {"id": "f" * 64, "model_running": True, "volume_data": b"keep"}
    docker = SimpleNamespace(items=items, daemon="docker-engine-original", actions=[], fail_stop=False)

    def execute(argv, **kwargs):
        assert argv[0] == "docker"
        args = argv[1:]
        if args[:1] == ["info"]:
            output = docker.daemon
        elif args[:1] == ["inspect"]:
            output = json.dumps([docker.items[x] for x in args[1:]])
        elif args[:3] == ["stop", "--time", "10"]:
            docker.actions.append(args)
            if docker.fail_stop:
                raise subprocess.CalledProcessError(1, argv)
            output = ""
        elif args[:1] == ["rm"]:
            docker.actions.append(args)
            for identity in args[1:]:
                del docker.items[identity]
            output = ""
        else:
            pytest.fail(f"Unexpected Docker operation: {args}")
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    monkeypatch.setattr("desktop_project.subprocess.run", execute)
    engine = DockerEngine(("docker",), {})

    def owner():
        return DesktopProject(config, env, engine, lambda: "\n".join(docker.items), source)

    return SimpleNamespace(
        root=root,
        data=data,
        config=config,
        source=source,
        env=env,
        docker=docker,
        owner=owner,
        unrelated=unrelated,
    )


def recorded(station):
    owner = station.owner()
    owner.capture()
    return owner


def test_reboot_recovers_only_registered_containers_and_preserves_everything_else(installation):
    station = installation
    first = recorded(station)
    receipt = station.root / RECEIPT
    text = receipt.read_text()
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert not receipt.is_relative_to(station.data)
    assert "do-not-persist-this" not in text
    marker = station.data / "user-data"
    marker.write_bytes(b"original")
    outside = copy.deepcopy(station.unrelated)
    ids = list(station.docker.items)
    for item in station.docker.items.values():
        item["State"] = {"Pid": 9999, "StartedAt": "after-reboot"}
    later = station.owner()
    later.recover(ids)
    assert station.docker.actions == [["stop", "--time", "10", *ids], ["rm", *ids]]
    assert marker.read_bytes() == b"original" and station.unrelated == outside
    assert receipt.exists()  # Retain authority until the replacement startup succeeds.
    later.clear()
    assert not receipt.exists() and first.record is not None


def test_partial_prior_shutdown_recovers_only_surviving_registered_ids(installation):
    recorded(installation)
    installation.docker.items.pop(next(iter(installation.docker.items)))
    ids = list(installation.docker.items)
    installation.owner().recover(ids)
    assert installation.docker.actions[0] == ["stop", "--time", "10", *ids]


def test_legacy_or_unknown_container_is_never_adopted(installation):
    with pytest.raises(RuntimeError, match="no private"):
        installation.owner().recover(list(installation.docker.items))
    recorded(installation)
    fake = copy.deepcopy(next(iter(installation.docker.items.values())))
    fake["Id"] = "9" * 64
    installation.docker.items = {fake["Id"]: fake}
    with pytest.raises(ValueError, match="Unregistered"):
        installation.owner().recover(list(installation.docker.items))
    assert not installation.docker.actions


@pytest.mark.parametrize("change", ["daemon", "environment", "mount", "image", "service", "restart"])
def test_changed_registered_container_or_daemon_refuses_entire_batch_before_signals(installation, change):
    recorded(installation)
    item = list(installation.docker.items.values())[-1]
    if change == "daemon":
        installation.docker.daemon = "replacement-daemon"
    elif change == "environment":
        item["Config"]["Env"].append("OTHER=changed")
    elif change == "mount":
        item["Mounts"][0]["Source"] = "/other-private-station"
    elif change == "image":
        item["Image"] = "sha256:" + "b" * 64
    elif change == "service":
        item["Config"]["Labels"]["com.docker.compose.service"] = "foreign"
    else:
        item["HostConfig"]["RestartPolicy"]["Name"] = "always"
    with pytest.raises(ValueError):
        installation.owner().recover(list(installation.docker.items))
    assert not installation.docker.actions


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "shared", "oversized", "directory"])
def test_unsafe_native_receipt_cannot_grant_recovery_authority(installation, unsafe):
    recorded(installation)
    path = installation.root / RECEIPT
    if unsafe == "symlink":
        other = installation.root / "preserved"
        path.rename(other)
        path.symlink_to(other)
    elif unsafe == "hardlink":
        os.link(path, installation.root / "other")
    elif unsafe == "shared":
        path.chmod(0o644)
    elif unsafe == "oversized":
        path.write_text(" " * 16385)
    else:
        path.unlink()
        path.mkdir()
    with pytest.raises((ValueError, OSError)):
        installation.owner()
    assert not installation.docker.actions


def test_replaced_data_directory_and_changed_config_refuse_recovery(installation):
    recorded(installation)
    installation.data.rename(installation.root / "original-data")
    installation.data.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="different storage"):
        installation.owner()
    assert not installation.docker.actions


def test_failed_stop_preserves_receipt_and_does_not_remove_containers(installation):
    recorded(installation)
    path = installation.root / RECEIPT
    original = path.read_bytes()
    installation.docker.fail_stop = True
    with pytest.raises(subprocess.CalledProcessError):
        installation.owner().recover(list(installation.docker.items))
    assert path.read_bytes() == original and len(installation.docker.items) == 4
    assert len(installation.docker.actions) == 1


def test_new_inventory_needs_complete_services_and_actual_package_data(installation):
    next(iter(installation.docker.items.values()))["Config"]["Labels"][
        "com.docker.compose.project.working_dir"
    ] = "/foreign"
    with pytest.raises(ValueError, match="launched package"):
        installation.owner().capture()
    assert not (installation.root / RECEIPT).exists()


def test_modified_receipt_is_not_forgotten_during_shutdown(installation):
    owner = recorded(installation)
    path = installation.root / RECEIPT
    value = json.loads(path.read_text())
    value["daemon"] = "different-daemon"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="changed during shutdown"):
        owner.clear()
    assert path.exists()


@pytest.mark.parametrize(
    "text", ["--all", "a" * 64 + " " + "a" * 64, "x" * 64, "\n".join(f"{x:064x}" for x in range(5))]
)
def test_inventory_rejects_flags_invalid_or_duplicate_ids(text):
    with pytest.raises(ValueError):
        container_ids(text)


def test_packaged_supervisor_records_before_ready_and_forgets_after_successful_down(
    installation, monkeypatch
):
    import httpx
    import launch

    station = installation
    templates = copy.deepcopy(station.docker.items)
    station.docker.items.clear()
    env = {**station.env, "AI_STATION_DESKTOP_INSTANCE_ID": "d" * 32}
    monkeypatch.setattr(launch, "ROOT", station.source)
    monkeypatch.setattr(launch, "configuration", lambda config: env)
    monkeypatch.setattr(
        launch.sys, "argv", ["launch.py", "--desktop", "--no-build", "--config", str(station.config)]
    )
    monkeypatch.setattr(launch.os, "chdir", lambda _: None)
    monkeypatch.setattr(launch.signal, "signal", lambda *args: None)
    monkeypatch.setattr(launch, "runner_health", lambda _: True)
    # Keep subprocess waiting independent of the simulated supervisor Ctrl+C.
    monkeypatch.setattr(
        launch,
        "time",
        SimpleNamespace(
            monotonic=launch.time.monotonic, sleep=lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
        ),
    )
    original = launch.subprocess.run
    operations = []

    def execute(argv, **kwargs):
        if argv[:2] != ["docker", "compose"]:
            return original(argv, **kwargs)
        if "ps" in argv:
            text = "\n".join(station.docker.items)
        elif "up" in argv:
            station.docker.items.update(copy.deepcopy(templates))
            operations.append("up")
            text = ""
        elif "down" in argv:
            assert (station.root / RECEIPT).is_file()
            assert "--volumes" not in argv and "-v" not in argv
            station.docker.items.clear()
            operations.append("down")
            text = ""
        else:
            pytest.fail(f"Unexpected compose command: {argv}")
        return subprocess.CompletedProcess(argv, 0, stdout=text)

    monkeypatch.setattr(launch.subprocess, "run", execute)
    real_client = httpx.Client

    def reply(request):
        assert len(json.loads((station.root / RECEIPT).read_text())["containers"]) == 4
        return httpx.Response(
            200, json={"status": "ok", "desktop_instance_id": "d" * 32, "setup_required": False}
        )

    monkeypatch.setattr(
        launch.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(reply), **kwargs)
    )
    launch.main()
    assert operations == ["up", "down"] and not (station.root / RECEIPT).exists()


def test_live_supervisor_lock_prevents_recovery_before_any_docker_operation(installation, monkeypatch):
    import fcntl

    import launch

    station = installation
    recorded(station)
    runtime = station.data / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(launch, "ROOT", station.source)
    monkeypatch.setattr(launch, "configuration", lambda config: station.env)
    monkeypatch.setattr(
        launch.sys, "argv", ["launch.py", "--desktop", "--no-build", "--config", str(station.config)]
    )
    monkeypatch.setattr(launch.os, "chdir", lambda _: None)
    monkeypatch.setattr(
        launch.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Live owner must exclude all Docker operations"),
    )
    with (runtime / "launcher.lock").open("a") as live:
        fcntl.flock(live, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="already supervised"):
            launch.main()
    assert not station.docker.actions


def test_device_renumbering_after_reboot_retains_filesystem_and_directory_identity(installation, monkeypatch):
    import desktop_project

    recorded(installation)
    original = desktop_project.directory

    def remounted(path):
        info = original(path)
        return SimpleNamespace(st_mode=info.st_mode, st_ino=info.st_ino, st_dev=info.st_dev + 1000)

    monkeypatch.setattr(desktop_project, "directory", remounted)
    installation.owner().recover(list(installation.docker.items))
    assert len(installation.docker.actions) == 2


def test_replacement_filesystem_refuses_even_if_paths_and_inodes_match(installation, monkeypatch):
    import desktop_project

    recorded(installation)
    original = desktop_project.os.statvfs
    monkeypatch.setattr(
        desktop_project.os, "statvfs", lambda path: SimpleNamespace(f_fsid=original(path).f_fsid + 1)
    )
    with pytest.raises(ValueError, match="different storage"):
        installation.owner()
    assert not installation.docker.actions


def test_mount_inventory_order_does_not_falsely_change_ownership(installation):
    for item in installation.docker.items.values():
        item["Mounts"].append(
            {"Type": "bind", "Source": str(installation.data / "runtime/runner"), "Destination": "/runner"}
        )
    recorded(installation)
    for item in installation.docker.items.values():
        item["Mounts"].reverse()
    installation.owner().recover(list(installation.docker.items))
    assert len(installation.docker.actions) == 2


@pytest.mark.parametrize("field", ["Dns", "DnsOptions", "DnsSearch"])
def test_dns_default_null_and_empty_remain_equivalent_after_daemon_restart(installation, field):
    for item in installation.docker.items.values():
        item["HostConfig"][field] = None
    recorded(installation)
    for item in installation.docker.items.values():
        item["HostConfig"][field] = []
    installation.owner().recover(list(installation.docker.items))
    assert len(installation.docker.actions) == 2


def make_literal_schema_one_receipt(station):
    from desktop_project import digest

    for item in station.docker.items.values():
        item["HostConfig"].update(Dns=None, DnsOptions=None, DnsSearch=None)
    recorded(station)
    path = station.root / RECEIPT
    value = json.loads(path.read_text())
    value["schema"] = 1
    for identity, item in station.docker.items.items():
        raw = {k: item[k] for k in ["Config", "HostConfig", "Image"]}
        raw["Mounts"] = sorted(item["Mounts"], key=lambda m: json.dumps(m, sort_keys=True))
        value["containers"][identity]["fingerprint"] = digest(raw)
    path.write_text(json.dumps(value))
    return value


def test_literal_prior_receipt_accepts_exact_three_default_changes_and_upgrades_on_capture(installation):
    original = copy.deepcopy(installation.docker.items)
    make_literal_schema_one_receipt(installation)
    for item in installation.docker.items.values():
        item["HostConfig"].update(Dns=[], DnsOptions=[], DnsSearch=[])
    owner = installation.owner()
    owner.recover(list(installation.docker.items))
    assert len(installation.docker.actions) == 2
    installation.docker.items.update(original)
    owner.capture()
    assert json.loads((installation.root / RECEIPT).read_text())["schema"] == 2


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "field,value", [("Dns", ["8.8.8.8"]), ("DnsOptions", ["use-vc"]), ("DnsSearch", ["private.example"])]
)
def test_real_dns_policy_change_still_refuses_before_stopping_anything(installation, legacy, field, value):
    if legacy:
        make_literal_schema_one_receipt(installation)
    else:
        recorded(installation)
    for item in installation.docker.items.values():
        item["HostConfig"].update(Dns=[], DnsOptions=[], DnsSearch=[])
    next(iter(installation.docker.items.values()))["HostConfig"][field] = value
    with pytest.raises(ValueError, match="changed"):
        installation.owner().recover(list(installation.docker.items))
    assert not installation.docker.actions
