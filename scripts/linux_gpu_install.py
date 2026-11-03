"""Fixed native Ubuntu prerequisite action; no app/Runner/agent entry point."""

import fcntl
import grp
import hashlib
import json
import os
import platform
import pwd
import re
import stat
import sys
from pathlib import Path

import windows_gpu_bundle as bundle
from windows_gpu_install import atomic, canonical, read_json, run, trusted

APP = Path("/usr/lib/ai-station")
STORE = Path("/var/lib/ai-station-native-gpu")
CONFIG = Path("/etc/docker/daemon.json")
SOCKET = Path("/run/docker.sock")
RUNTIME = {"path": "/usr/bin/nvidia-container-runtime", "runtimeArgs": []}


def identity():
    if len(sys.argv) != 1 or os.getuid() != 0 or os.geteuid() != 0:
        raise ValueError("Use the native operating-system authentication dialog")
    invoking = os.environ.get("PKEXEC_UID", "")
    if not re.fullmatch(r"[1-9][0-9]{3,9}", invoking) or not 1000 <= int(invoking) < 2**32:
        raise ValueError("A normal invoking account is required")
    account = pwd.getpwuid(int(invoking))
    if account.pw_uid != int(invoking):
        raise ValueError("The invoking account changed")
    if (
        platform.system() != "Linux"
        or platform.machine().lower() not in {"x86_64", "amd64"}
        or "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
        or platform.freedesktop_os_release().get("ID") != "ubuntu"
        or platform.freedesktop_os_release().get("VERSION_ID") != "24.04"
    ):
        raise ValueError("Automatic graphics preparation requires native Ubuntu 24.04 x86-64")
    socket = SOCKET.lstat()
    group = grp.getgrnam("docker")
    if (
        not stat.S_ISSOCK(socket.st_mode)
        or socket.st_uid != 0
        or socket.st_gid != group.gr_gid
        or group.gr_gid == 0
        or stat.S_IMODE(socket.st_mode) != 0o660
    ):
        raise ValueError("Use the existing system Docker Engine; its socket was not changed")
    for path in (APP, *APP.parents, APP / "scripts", APP / "windows-gpu"):
        trusted(path, directory=True)
    for name in ("linux_gpu_install.py", "windows_gpu_install.py", "windows_gpu_bundle.py"):
        trusted(APP / "scripts" / name)
    manifest = read_json(APP / "desktop-manifest.json", limit=16 * 1024**2)
    if manifest.get("linux_gpu_recipe") != bundle.RECIPE:
        raise ValueError("Install the reviewed native Linux graphics package")
    bundle.verify(APP / "windows-gpu")
    for path in (APP / "windows-gpu").iterdir():
        trusted(path)
    return account.pw_uid


def docker(*args):
    return run(
        "/usr/bin/docker", "--host", "unix:///run/docker.sock", "--config", str(STORE / "client"), *args
    )


def daemon():
    main = run("/usr/bin/systemctl", "show", "--property=MainPID", "--value", "docker.service")
    if not main.isdigit() or int(main) <= 1:
        raise ValueError("The system Docker service must already be running")
    if (Path("/proc") / main / "exe").resolve() != Path("/usr/bin/dockerd").resolve():
        raise ValueError("The system Docker service has an unexpected executable")
    observed = json.loads(docker("info", "--format", "{{json .}}"))
    if (
        not isinstance(observed, dict)
        or not isinstance(observed.get("ID"), str)
        or not re.fullmatch(r"[A-Za-z0-9:_-]{8,128}", observed["ID"])
        or observed.get("OSType") != "linux"
        or observed.get("DefaultRuntime") != "runc"
        or not isinstance(observed.get("SecurityOptions"), list)
        or any("rootless" in str(item) for item in observed["SecurityOptions"])
    ):
        raise ValueError("This Docker configuration needs inspection; nothing was reconfigured")
    return observed["ID"]


def configuration():
    for path in CONFIG.parent.parents:
        trusted(path, directory=True)
    CONFIG.parent.mkdir(mode=0o755, exist_ok=True)
    trusted(CONFIG.parent, directory=True)
    exists = CONFIG.exists() or CONFIG.is_symlink()
    value = read_json(CONFIG) if exists else {}
    original = CONFIG.read_bytes() if exists else None
    if not isinstance(value.get("runtimes", {}), dict) or value.get("default-runtime", "runc") != "runc":
        raise ValueError("Preserve the existing custom Docker configuration")
    runtimes = value.get("runtimes", {})
    if "nvidia" in runtimes and runtimes["nvidia"] != RUNTIME:
        raise ValueError("Preserve the existing NVIDIA runtime configuration")
    return original, canonical({**value, "runtimes": {**runtimes, "nvidia": RUNTIME}})


def packages():
    import subprocess

    result = {}
    for name, *_ in bundle.PACKAGES:
        try:
            value = run("/usr/bin/dpkg-query", "--show", "--showformat=${db:Status-Status} ${Version}", name)
        except subprocess.CalledProcessError as error:
            if error.returncode != 1:
                raise
            value = ""
        if value:
            status, version = value.split(" ", 1)
            result[name] = (status, version)
    return result


def existing_tools():
    return any(
        path.exists() or path.is_symlink()
        for path in (
            Path("/etc/nvidia-container-runtime"),
            Path("/usr/bin/nvidia-ctk"),
            Path("/usr/bin/nvidia-container-runtime"),
        )
    )


def install():
    invoking = identity()
    for path in STORE.parents:
        trusted(path, directory=True)
    STORE.mkdir(mode=0o700, exist_ok=True)
    trusted(STORE, directory=True, private=True)
    descriptor = os.open(STORE / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        trusted(STORE / "operation.lock", private=True)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client = STORE / "client"
        client.mkdir(mode=0o700, exist_ok=True)
        trusted(client, directory=True, private=True)
        atomic(client / "config.json", b"{}")
        engine = daemon()
        original, target = configuration()
        receipt = STORE / "receipt.json"
        saved = read_json(receipt) if receipt.exists() or receipt.is_symlink() else None
        installed = packages()
        complete = {name: ("installed", bundle.VERSION) for name, *_ in bundle.PACKAGES}
        target_hash = hashlib.sha256(target).hexdigest()
        if saved is not None:
            if (
                saved.get("recipe") != bundle.RECIPE
                or saved.get("phase") not in {"installing", "prepared"}
                or saved.get("daemon") != engine
                or saved.get("target_sha256") != target_hash
                or any(version != bundle.VERSION for _, version in installed.values())
            ):
                raise ValueError("A changed graphics operation needs inspection")
        elif installed or existing_tools():
            raise ValueError("Existing graphics tools are preserved; inspect their configuration")
        journal = {
            "schema": 1,
            "recipe": bundle.RECIPE,
            "phase": "installing",
            "daemon": engine,
            "invoking_uid": invoking,
            "original_sha256": saved["original_sha256"]
            if saved
            else hashlib.sha256(original).hexdigest()
            if original is not None
            else None,
            "target_sha256": target_hash,
        }
        backup = STORE / "original-daemon.json"
        if journal["original_sha256"] is not None:
            if backup.exists() or backup.is_symlink():
                trusted(backup, private=True)
                if hashlib.sha256(backup.read_bytes()).hexdigest() != journal["original_sha256"]:
                    raise ValueError("The original Docker configuration backup changed")
            elif saved is not None or original is None:
                raise ValueError("The original configuration backup requires inspection")
            else:
                atomic(backup, original)
        elif backup.exists() or backup.is_symlink():
            raise ValueError("An unexpected original configuration must be preserved")
        current_hash = hashlib.sha256(original).hexdigest() if original is not None else None
        if saved and current_hash not in {saved["original_sha256"], target_hash}:
            raise ValueError("Docker settings changed during graphics preparation")
        if saved and saved["phase"] == "prepared":
            if installed != complete or current_hash != target_hash:
                raise ValueError("The prepared graphics configuration changed")
            return {"status": "prepared", "restart_required": True, "gpu_ready": False}
        atomic(receipt, canonical(journal))
        if installed != complete:
            run(
                "/usr/bin/dpkg",
                "--install",
                *(str(APP / "windows-gpu" / p["filename"]) for p in bundle.metadata()["packages"]),
                timeout=300,
            )
        if packages() != complete or daemon() != engine:
            raise ValueError("The graphics package/daemon identity could not be confirmed")
        stage = STORE / "daemon.next.json"
        atomic(stage, target)
        run("/usr/bin/dockerd", "--validate", "--config-file", str(stage))
        current = CONFIG.read_bytes() if CONFIG.exists() or CONFIG.is_symlink() else None
        if current != original:
            raise ValueError("Docker settings changed before publication")
        atomic(CONFIG, target, mode=0o644)
        stage.unlink()
        atomic(receipt, canonical({**journal, "phase": "prepared"}))
        # Never restart/reload the host daemon or signal any container. A normal
        # operator-chosen OS restart activates its hook; native CUDA probing, not
        # this prerequisite receipt, decides actual GPU readiness afterward.
        return {"status": "prepared", "restart_required": True, "gpu_ready": False}
    finally:
        os.close(descriptor)


def main():
    import subprocess

    try:
        print(json.dumps(install()), flush=True)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        print(
            "Graphics preparation needs inspection; existing work and its receipt were preserved",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
