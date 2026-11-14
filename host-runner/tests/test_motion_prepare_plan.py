"""Offline ownership/authority checks; no Docker, network or model invocation."""

import copy
import io
import tarfile
from uuid import uuid4

import pytest
from ai_station_runner.motion_prepare_plan import BASES, inspect_owned, manifest, source_archive, stage_spec


@pytest.fixture(params=["sdk", "runtime"])
def owned(request):
    stage, identity, request_hash = request.param, str(uuid4()), "a" * 64
    base = {
        "Id": "sha256:" + "b" * 64,
        "RepoDigests": [BASES[stage]],
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {"Env": ["PATH=/usr/local/bin:/usr/bin:/bin"], "User": "", "Entrypoint": None},
    }
    spec = stage_spec(stage, identity, request_hash)
    config = {key: value for key, value in spec.items() if key != "HostConfig"}
    value = {
        "Id": "c" * 64,
        "Image": base["Id"],
        "Config": {**copy.deepcopy(base["Config"]), **config},
        "HostConfig": copy.deepcopy(spec["HostConfig"]),
        "Mounts": [],
    }
    return value, base, stage, identity, request_hash


def check(owned):
    return inspect_owned(*owned, container_id="c" * 64)


def test_owned_fixed_cpu_stage_accepts_only_its_verified_identity(owned):
    value = check(owned)
    assert not value["Mounts"]
    assert value["HostConfig"]["Memory"] == value["HostConfig"]["MemorySwap"]
    with pytest.raises(ValueError):
        inspect_owned(*owned, container_id="d" * 64)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("Config", "Cmd", ["sh", "-c", "id"]),
        ("Config", "Env", ["DOCKER_HOST=tcp://other:2375"]),
        ("Config", "Entrypoint", ["/unreviewed/program"]),
        ("Config", "User", "another-user"),
        ("Config", "WorkingDir", "/unreviewed"),
        ("Config", "Image", "python:latest"),
        ("Config", "Labels", {"ai-station.motion.prepare.run": str(uuid4())}),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "MemorySwap", -1),
        ("HostConfig", "OomKillDisable", True),
        ("HostConfig", "CpuQuota", 0),
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "CapDrop", []),
        ("HostConfig", "SecurityOpt", []),
        ("HostConfig", "Binds", ["/:/host"]),
        ("HostConfig", "Devices", [{"PathOnHost": "/dev/nvidia0"}]),
        ("HostConfig", "DeviceRequests", [{"Driver": "nvidia"}]),
        ("HostConfig", "PortBindings", {"80/tcp": [{"HostPort": "80"}]}),
        ("HostConfig", "PidMode", "host"),
        ("HostConfig", "IpcMode", "host"),
        ("HostConfig", "Runtime", "nvidia"),
        ("HostConfig", "AutoRemove", True),
        ("HostConfig", "RestartPolicy", {"Name": "always"}),
    ],
)
def test_changed_container_cannot_be_adopted_or_signaled(owned, section, key, value):
    owned[0][section][key] = value
    with pytest.raises(ValueError):
        check(owned)


def test_host_mount_or_unpinned_base_cannot_be_adopted(owned):
    owned[0]["Mounts"] = [{"Source": "/var/run/docker.sock", "Destination": "/docker.sock"}]
    with pytest.raises(ValueError):
        check(owned)
    owned[0]["Mounts"] = []
    owned[1]["RepoDigests"] = ["unreviewed@sha256:" + "b" * 64]
    with pytest.raises(ValueError):
        check(owned)


@pytest.mark.parametrize(
    "stage,identity,receipt",
    [("shell", str(uuid4()), "a" * 64), ("sdk", "../other", "a" * 64), ("sdk", str(uuid4()), "shell")],
    ids=["unapproved-stage", "escaping-identity", "invalid-receipt"],
)
def test_callers_cannot_select_a_program_or_path(stage, identity, receipt):
    with pytest.raises(ValueError):
        stage_spec(stage, identity, receipt)


def test_packaged_archives_are_finite_and_readable_without_host_uid_authority():
    for stage in BASES:
        with tarfile.open(fileobj=io.BytesIO(source_archive(stage))) as archive:
            files = archive.getmembers()
            assert files and all(item.isfile() for item in files)
            assert all(item.uid == item.gid == 0 and item.mode == 0o644 for item in files)
            assert all(item.name.startswith("opt/") and ".." not in item.name.split("/") for item in files)
            assert sum(item.size for item in files) <= 4 * 1024**2
            assert not any("secret" in item.name or "env" in item.name for item in files)
    assert manifest() == manifest()
    with pytest.raises(ValueError):
        source_archive("/home/someone")
