"""Fixed offline toolkit activation inside the owned guest, never a Runner operation."""

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Isolated packaged Python ignores ambient paths. This trusted installer script
# and its companion are part of the same root-owned immutable application.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import windows_gpu_bundle as bundle  # noqa: E402

APP = Path("/usr/lib/ai-station")
STORE = Path("/var/lib/ai-station-gpu")
CONFIG = Path("/etc/docker/daemon.json")
RECEIPT = Path("/usr/lib/ai-station-wsl-build.json")
RUNTIME = {"path": "/usr/bin/nvidia-container-runtime", "runtimeArgs": []}
ENVIRONMENT = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "DEBIAN_FRONTEND": "noninteractive",
}


def trusted(path, *, directory=False, private=False, uid=0):
    info = path.lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if not valid or info.st_uid != uid or info.st_mode & (0o077 if private else 0o022):
        raise ValueError("Guest installation files must remain root-owned and protected")
    return info


def object_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate guest configuration field")
        result[key] = value
    return result


def read_json(path, *, limit=65536):
    if trusted(path).st_size > limit:
        raise ValueError("Guest configuration exceeds its fixed bound")
    value = json.loads(path.read_bytes(), object_pairs_hook=object_fields)
    if not isinstance(value, dict):
        raise ValueError("Guest configuration must be an object")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def atomic(path, data, *, mode=0o600):
    trusted(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        trusted(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".gpu-", delete=False) as output:
        stage = Path(output.name)
        try:
            output.write(data)
            os.fchmod(output.fileno(), mode)
            output.flush()
            os.fsync(output.fileno())
            os.replace(stage, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            stage.unlink(missing_ok=True)


def run(*argv, timeout=30):
    # No caller-controlled commands, environment, shell or OS installation target.
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(
            argv,
            stdout=output,
            stderr=subprocess.DEVNULL,
            env=ENVIRONMENT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            child.wait(timeout=timeout)
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=2)
            raise
        if child.returncode:
            raise subprocess.CalledProcessError(child.returncode, argv)
        output.seek(0)
        data = output.read(1024**2 + 1)
        if len(data) > 1024**2:
            raise ValueError("Guest command output exceeded its fixed bound")
        return data.decode().strip()


def assert_guest(distribution=None, *, image_build=False):
    if os.getuid() != 0 or os.geteuid() != 0:
        raise ValueError("Only the dedicated guest installer can activate its toolkit")
    if not image_build:
        if not isinstance(distribution, str) or re.fullmatch(r"AIStation-[a-f0-9]{32}", distribution) is None:
            raise ValueError("Use the accepted owned distribution identity")
        if "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower():
            raise ValueError("Toolkit activation belongs only to the owned WSL guest")
    for path in [APP, *APP.parents, APP / "scripts", APP / "windows-gpu", RECEIPT.parent]:
        trusted(path, directory=True)
    trusted(APP / "scripts/windows_gpu_install.py")
    trusted(APP / "scripts/windows_gpu_bundle.py")
    receipt = read_json(RECEIPT)
    if receipt.get("desktop_protocol") != 2 or receipt.get("package", {}).get("Package") != "ai-station":
        raise ValueError("The guest installation receipt is not an accepted AI Station package")
    if receipt.get("package", {}).get("X-AI-Station-WSL-GPU-Recipe") != bundle.RECIPE:
        # During an old-to-new update the rootfs receipt intentionally stays at
        # the old package until all activation checks have completed.
        if image_build:
            raise ValueError("The guest image lacks its accepted GPU package recipe")
    if image_build:
        trusted(Path("/.dockerenv"))
        if (
            Path("/usr/sbin/policy-rc.d").read_text() != "#!/bin/sh\nexit 101\n"
            or Path("/run/systemd/system").exists()
        ):
            raise ValueError("Build toolkit inputs only in the daemon-free guest image build")
    account = pwd.getpwnam("station")
    if account.pw_uid < 1000 or account.pw_dir != "/home/station":
        raise ValueError("The dedicated guest account changed")
    trusted_home = Path(account.pw_dir).lstat()
    if (
        not stat.S_ISDIR(trusted_home.st_mode)
        or trusted_home.st_uid != account.pw_uid
        or trusted_home.st_mode & 0o077
    ):
        raise ValueError("The dedicated guest home must stay private")
    # Verify the newly installed immutable package, independently of the old
    # rootfs receipt. This runs before any package or daemon modification.
    manifest = read_json(APP / "desktop-manifest.json", limit=16 * 1024**2)
    if manifest.get("windows_gpu_recipe") != bundle.RECIPE:
        raise ValueError("The installed application lacks the reviewed toolkit inputs")
    bundle.verify(APP / "windows-gpu")
    for path in (APP / "windows-gpu").iterdir():
        trusted(path)


def configuration():
    for parent in CONFIG.parent.parents:
        trusted(parent, directory=True)
    CONFIG.parent.mkdir(mode=0o755, exist_ok=True)
    trusted(CONFIG.parent, directory=True)
    value = read_json(CONFIG) if CONFIG.exists() or CONFIG.is_symlink() else {}
    original = CONFIG.read_bytes() if CONFIG.exists() else None
    if not isinstance(value, dict) or not isinstance(value.get("runtimes", {}), dict):
        raise ValueError("Inspect the existing owned Docker configuration")
    runtimes = dict(value.get("runtimes", {}))
    if "nvidia" in runtimes and runtimes["nvidia"] != RUNTIME:
        raise ValueError("An existing different NVIDIA runtime must be preserved")
    runtimes["nvidia"] = RUNTIME
    target = {**value, "runtimes": runtimes, "live-restore": True}
    return original, canonical(target)


def docker(*args):
    return run(
        "/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "--config", str(STORE / "client"), *args
    )


def running():
    identifiers = docker("ps", "--quiet", "--no-trunc").splitlines()
    if len(identifiers) > 128 or any(re.fullmatch(r"[a-f0-9]{64}", value) is None for value in identifiers):
        raise ValueError("Inspect the existing guest containers before updating")
    result = {}
    for identifier in identifiers:
        state = json.loads(docker("inspect", "--format", "{{json .State}}", identifier))
        if state.get("Running") is not True or type(state.get("Pid")) is not int or state["Pid"] <= 0:
            raise ValueError("An existing guest container is changing state")
        if not isinstance(state.get("StartedAt"), str) or len(state["StartedAt"]) > 100:
            raise ValueError("An existing guest container lacks its process identity")
        result[identifier] = {"pid": state["Pid"], "started_at": state["StartedAt"]}
    return result


def daemon():
    live_restore = json.loads(docker("info", "--format", "{{json .LiveRestoreEnabled}}"))
    runtimes = json.loads(docker("info", "--format", "{{json .Runtimes}}"))
    if type(live_restore) is not bool or not isinstance(runtimes, dict):
        raise ValueError("The owned Docker daemon did not confirm its configuration")
    return live_restore, "nvidia" in runtimes


def wait_ready(*, require_runtime):
    deadline = time.monotonic() + 30
    while True:
        try:
            live_restore, registered = daemon()
            if live_restore and (registered or not require_runtime):
                return
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("The owned Docker daemon is not ready; preserve the pending update")
        time.sleep(0.2)


def installed_packages():
    expected = {p[0]: bundle.VERSION for p in bundle.PACKAGES}
    try:
        value = run(
            "/usr/bin/dpkg-query",
            "--show",
            "--showformat=${Package} ${db:Status-Status} ${Version}\n",
            *expected,
        )
    except subprocess.CalledProcessError:
        return False
    return sorted(value.splitlines()) == sorted(
        f"{name} installed {version}" for name, version in expected.items()
    )


def install(distribution=None, *, image_build=False):
    assert_guest(distribution, image_build=image_build)
    for parent in STORE.parents:
        trusted(parent, directory=True)
    STORE.mkdir(mode=0o700, exist_ok=True)
    trusted(STORE, directory=True, private=True)
    client = STORE / "client"
    client.mkdir(mode=0o700, exist_ok=True)
    trusted(client, directory=True, private=True)
    atomic(client / "config.json", b"{}")
    descriptor = os.open(STORE / "install.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        trusted(STORE / "install.lock", private=True)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original, target = configuration()
        receipt_path = STORE / "receipt.json"
        receipt = read_json(receipt_path) if receipt_path.exists() or receipt_path.is_symlink() else None
        if receipt is not None and (
            receipt.get("recipe") != bundle.RECIPE
            or receipt.get("phase") not in {"installing", "complete", "image_prepared"}
        ):
            raise ValueError("A different guest toolkit operation requires inspection")
        if not image_build:
            if (
                run("/usr/bin/systemctl", "show", "--property=KillMode", "--value", "docker.service")
                != "process"
            ):
                raise ValueError("The owned Docker unit cannot preserve its running container processes")
            before = running()
            if (
                receipt is not None
                and receipt["phase"] == "installing"
                and receipt.get("running_before") != before
            ):
                raise ValueError("Existing container identities changed during toolkit activation")
        else:
            before = {}
        if receipt is not None and receipt["phase"] in {"complete", "image_prepared"}:
            if not installed_packages() or original != target:
                raise ValueError("The completed guest toolkit configuration changed; inspect before updating")
            if not image_build:
                wait_ready(require_runtime=True)
            return {"status": "ready", "recipe": bundle.RECIPE, "gpu_inference_verified": False}
        journal = {
            "recipe": bundle.RECIPE,
            "phase": "installing",
            "running_before": before,
            "target_sha256": hashlib.sha256(target).hexdigest(),
            "original_sha256": receipt.get("original_sha256")
            if receipt is not None
            else hashlib.sha256(original).hexdigest()
            if original is not None
            else None,
        }
        if receipt is not None and receipt.get("target_sha256") != journal["target_sha256"]:
            raise ValueError("The pending guest toolkit configuration changed")
        atomic(receipt_path, canonical(journal))
        backup = STORE / "original-daemon.json"
        if journal["original_sha256"] is not None:
            if backup.exists() or backup.is_symlink():
                trusted(backup, private=True)
                if hashlib.sha256(backup.read_bytes()).hexdigest() != journal["original_sha256"]:
                    raise ValueError("The original guest Docker configuration backup changed")
            else:
                if original is None or hashlib.sha256(original).hexdigest() != journal["original_sha256"]:
                    raise ValueError("The original guest Docker configuration is no longer available")
                atomic(backup, original)
        elif backup.exists() or backup.is_symlink():
            raise ValueError("An unexpected guest Docker configuration backup must be preserved")
        if not installed_packages():
            run(
                "/usr/bin/dpkg",
                "--install",
                *(str(APP / "windows-gpu" / p["filename"]) for p in bundle.metadata()["packages"]),
                timeout=300,
            )
        if not installed_packages():
            raise ValueError("The offline toolkit installation did not verify")
        stage = STORE / "daemon.next.json"
        atomic(stage, target)
        run("/usr/bin/dockerd", "--validate", "--config-file", str(stage))
        atomic(CONFIG, target, mode=0o644)
        stage.unlink()
        if not image_build:
            run("/usr/bin/systemctl", "reload", "docker.service")
            wait_ready(require_runtime=False)
            if running() != before:
                raise ValueError("Existing container processes changed before daemon activation")
            run("/usr/bin/systemctl", "restart", "docker.service")
            wait_ready(require_runtime=True)
            if running() != before:
                raise ValueError("Existing container processes were not preserved through daemon activation")
        atomic(receipt_path, canonical({**journal, "phase": "image_prepared" if image_build else "complete"}))
        return {"status": "ready", "recipe": bundle.RECIPE, "gpu_inference_verified": False}
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image-build", action="store_true")
    group.add_argument("--distribution")
    args = parser.parse_args()

    def interrupted(_number, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    print(json.dumps(install(args.distribution, image_build=args.image_build)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, KeyboardInterrupt):
        raise SystemExit(
            "Guest toolkit activation did not complete. Saved work and pending update were preserved."
        ) from None
