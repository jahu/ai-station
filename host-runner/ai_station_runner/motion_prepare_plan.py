"""Closed CPU preparation policy; no public installation endpoint or shell input.

The durable setup coordinator must own these stages before exposing fresh setup.
Only the two built-in official manifests and packaged renderer sources are used.
"""

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from uuid import UUID

from ai_station_runner.motion_image import FILES, RESOURCE, recipe

MEMORY = 2 * 1024**3
BASES = {
    "sdk": "node@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d",
    "runtime": "python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df",
}
COMMANDS = {
    "sdk": ["npm", "ci", "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"],
    "runtime": [
        "/bin/sh",
        "-ec",
        "apt-get update && apt-get install -y --no-install-recommends chromium ffmpeg"
        " && rm -rf /var/lib/apt/lists/*"
        " && pip install --no-cache-dir pydantic==2.13.5 pillow==12.3.0"
        " && mkdir -p /opt/ai-station /work",
    ],
}
CAPS = {"sdk": [], "runtime": ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"]}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stage_spec(stage, identity, request_hash):
    if stage not in BASES or not re.fullmatch(r"[a-f0-9]{64}", request_hash):
        raise ValueError("Use a fixed renderer preparation stage and request identity")
    identity = str(UUID(str(identity)))
    return {
        "Image": BASES[stage],
        "Cmd": list(COMMANDS[stage]),
        "WorkingDir": "/opt/sdk" if stage == "sdk" else "/work",
        "Labels": {
            "ai-station.motion.prepare.run": identity,
            "ai-station.motion.prepare.request": request_hash,
            "ai-station.motion.prepare.stage": stage,
            "ai-station.motion.prepare.renderer": recipe(),
        },
        "HostConfig": {
            "Memory": MEMORY,
            "MemorySwap": MEMORY,
            "CpuPeriod": 100000,
            "CpuQuota": 200000,
            "PidsLimit": 256,
            "NetworkMode": "bridge",
            "IpcMode": "private",
            "Runtime": "runc",
            "CapDrop": ["ALL"],
            "CapAdd": list(CAPS[stage]),
            "SecurityOpt": ["no-new-privileges:true"],
            "RestartPolicy": {"Name": "no"},
        },
    }


def inspect_owned(value, base, stage, identity, request_hash, *, container_id):
    """Refuse altered command, resource, network, mount or image ownership."""
    spec = stage_spec(stage, identity, request_hash)
    config, host = value.get("Config") or {}, value.get("HostConfig") or {}
    if (
        not re.fullmatch(r"[a-f0-9]{64}", container_id)
        or value.get("Id") != container_id
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", base.get("Id", ""))
        or value.get("Image") != base["Id"]
        or spec["Image"] not in (base.get("RepoDigests") or [])
        or base.get("Os") != "linux"
        or base.get("Architecture") != "amd64"
        or config.get("Image") != spec["Image"]
        or config.get("Cmd") != spec["Cmd"]
        or config.get("WorkingDir") != spec["WorkingDir"]
        or config.get("User", "") != base["Config"].get("User", "")
        or config.get("Entrypoint") != base["Config"].get("Entrypoint")
        or config.get("Env") != base["Config"].get("Env")
        or config.get("Labels") != {**(base["Config"].get("Labels") or {}), **spec["Labels"]}
        or value.get("Mounts")
        or config.get("Volumes")
        or config.get("ExposedPorts")
    ):
        raise ValueError("Renderer preparation source or container ownership changed")
    expected = spec["HostConfig"]
    for key in ("Memory", "MemorySwap", "CpuPeriod", "CpuQuota", "PidsLimit", "NetworkMode"):
        if host.get(key) != expected[key]:
            raise ValueError("Renderer preparation resource or network policy changed")
    for key in ("CapAdd", "CapDrop", "SecurityOpt"):
        if sorted(host.get(key) or []) != sorted(expected[key]):
            raise ValueError("Renderer preparation privileges changed")
    if (
        host.get("Privileged")
        or host.get("Binds")
        or host.get("Mounts")
        or host.get("Tmpfs")
        or host.get("Devices")
        or host.get("DeviceRequests")
        or host.get("PortBindings")
        or host.get("PublishAllPorts")
        or host.get("VolumesFrom")
        or host.get("PidMode")
        or host.get("IpcMode") not in {"", "private"}
        or host.get("AutoRemove")
        or (host.get("RestartPolicy") or {}).get("Name", "no") not in {"", "no"}
        or host.get("Runtime", "runc") != "runc"
    ):
        raise ValueError("Renderer preparation cannot acquire host, GPU or shared namespace access")
    return value


def source_archive(stage):
    """Only packaged public sources, root-owned within the target container.

    Docker archive copy retains source ownership/modes; private host staging
    files must never become unreadable 0600/host-UID npm inputs in a capless stage.
    Nothing is unpacked onto the host and no user path enters this archive.
    """
    if stage == "sdk":
        entries = [(RESOURCE / name, "opt/sdk/" + name) for name in ("package.json", "package-lock.json")]
    elif stage == "runtime":
        entries = [
            (Path(__file__).with_name(name), "opt/ai-station/ai_station_runner/" + name) for name in FILES
        ]
    else:
        raise ValueError("Use a fixed renderer source stage")
    output, total = io.BytesIO(), 0
    with tarfile.open(fileobj=output, mode="w") as archive:
        for source, name in entries:
            if source.is_symlink() or not source.is_file():
                raise ValueError("Packaged renderer sources must be ordinary files")
            content = source.read_bytes()
            total += len(content)
            if total > 4 * 1024**2:
                raise ValueError("Packaged renderer preparation sources exceed their bound")
            item = tarfile.TarInfo(name)
            item.uid = item.gid = 0
            item.mode, item.size = 0o644, len(content)
            archive.addfile(item, io.BytesIO(content))
    return output.getvalue()


def manifest():
    policies = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("motion_prepare_plan.py", "motion_prepare_owner.py")
    }
    return {
        "bases": dict(BASES),
        "renderer_recipe": recipe(),
        "policy_sha256": fingerprint(policies),
        "policy_files": policies,
        "archives": {stage: hashlib.sha256(source_archive(stage)).hexdigest() for stage in BASES},
        "stage_memory_mib": MEMORY // 1024**2,
        "parallel_stages": False,
    }
