"""Offline package update inside the dedicated WSL guest; no HTTP or agent entry point.

The trusted Windows installer will stream its verified package to this program.
This layer is not wired into the consumer installer until native transport and
recovery qualification pass. Never invoke it on the development host.
"""

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

APP = Path("/usr/lib/ai-station")
HOME = Path("/home/station")
RECEIPT = Path("/usr/lib/ai-station-wsl-build.json")
BRIDGE = Path("/usr/libexec/ai-station/wsl-control")
STORE = Path("/var/lib/ai-station-updates")
PENDING_MARKER = Path("/usr/lib/ai-station-wsl-update-pending.json")
TERMINAL = ("succeeded", "failed", "canceled", "interrupted")


def regular(path, uid, *, private=False):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != uid
        or info.st_nlink != 1
        or info.st_mode & (0o077 if private else 0o022)
    ):
        raise ValueError("An update file is not a trusted regular file")
    return info


def directory(path, uid, *, private=False):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & (0o077 if private else 0o022):
        raise ValueError("An update directory has unsafe ownership or permissions")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate update metadata field")
        result[key] = value
    return result


def read_json(path, uid):
    if regular(path, uid).st_size > 65536:
        raise ValueError("Update metadata exceeds its limit")
    return json.loads(path.read_bytes(), object_pairs_hook=strict_object)


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".update-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(canonical_json(value))
            output.flush()
            os.fsync(output.fileno())
            if path.exists() or path.is_symlink():
                regular(path, os.geteuid())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


def identity(value):
    """Only the immutable guest-build fields, excluding Windows archive receipts."""
    keys = {"schema", "desktop_protocol", "source_head", "base", "package_sha256", "package", "sources"}
    if not isinstance(value, dict) or not keys.issubset(value):
        raise ValueError("Incomplete guest package identity")
    result = {key: value[key] for key in keys}
    if (
        type(result["schema"]) is not int
        or result["schema"] != 1
        or type(result["desktop_protocol"]) is not int
        or result["desktop_protocol"] != 2
        or not isinstance(result["source_head"], str)
        or re.fullmatch(r"[a-f0-9]{40}", result["source_head"]) is None
        or not isinstance(result["package_sha256"], str)
        or re.fullmatch(r"[a-f0-9]{64}", result["package_sha256"]) is None
        or not isinstance(result["base"], str)
        or re.fullmatch(r"ubuntu:24\.04@sha256:[a-f0-9]{64}", result["base"]) is None
    ):
        raise ValueError("Invalid guest package identity")
    package = result["package"]
    if (
        not isinstance(package, dict)
        or package.get("Package") != "ai-station"
        or package.get("Architecture") != "amd64"
        or package.get("X-AI-Station-Desktop-Protocol") != "2"
        or not isinstance(package.get("Version"), str)
        or re.fullmatch(r"0\.1\.0~preview\.[0-9]+\+[a-f0-9]{16}", package["Version"]) is None
    ):
        raise ValueError("Only the reviewed AI Station desktop package can be updated")
    sources = result["sources"]
    if not isinstance(sources, dict) or set(sources) != {"guest.Dockerfile", "guest_control.py", "wsl.conf"}:
        raise ValueError("Incomplete guest source identities")
    if any(not isinstance(v, str) or re.fullmatch(r"[a-f0-9]{64}", v) is None for v in sources.values()):
        raise ValueError("Invalid guest source identity")
    return result


def plan(previous, target):
    previous, target = identity(previous), identity(target)
    if previous["base"] != target["base"] or any(
        previous["sources"][name] != target["sources"][name] for name in ("guest.Dockerfile", "wsl.conf")
    ):
        raise ValueError("This update requires a different guest OS recipe; preserve the existing distro")
    if previous["sources"]["guest_control.py"] != target["sources"]["guest_control.py"]:
        raise ValueError("A bridge protocol update requires its separately qualified migration")
    return {"previous": previous, "target": target}


@contextmanager
def locked(path, uid, *, create=False):
    if path.exists() or path.is_symlink():
        regular(path, uid, private=True)
    elif not create:
        yield
        return
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    if create:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            descriptor = os.open(path, flags)
        else:
            if os.geteuid() == 0 and uid != 0:
                os.fchown(descriptor, uid, -1)
    else:
        descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError("Unsafe update lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("AI Station is still active; stop it normally before updating") from None
        yield
    finally:
        os.close(descriptor)


def assert_host(distribution):
    if (
        os.getuid() != 0
        or os.geteuid() != 0
        or re.fullmatch(r"AIStation-[a-f0-9]{32}", distribution) is None
        or os.environ.get("WSL_DISTRO_NAME") != distribution
        or "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower()
    ):
        raise ValueError("Update only the explicitly owned WSL2 guest as its installer")
    account = pwd.getpwnam("station")
    if account.pw_uid < 1000 or Path(account.pw_dir) != HOME:
        raise ValueError("The dedicated guest account changed")
    for path in [Path("/"), Path("/usr"), Path("/usr/lib"), APP, RECEIPT.parent, BRIDGE.parent]:
        directory(path, 0)
    regular(APP / "station", 0)
    regular(BRIDGE, 0)
    directory(HOME, account.pw_uid, private=True)
    return account.pw_uid


def receive(source, destination, expected, size):
    if type(size) is not int or not 0 < size < 1024**3:
        raise ValueError("Invalid update package size")
    digest = hashlib.sha256()
    created = False
    try:
        with destination.open("xb") as output:
            created = True
            os.chmod(destination, 0o600)
            remaining = size
            while remaining:
                block = source.read(min(1024**2, remaining))
                if not block:
                    raise ValueError("The update transfer was interrupted")
                output.write(block)
                digest.update(block)
                remaining -= len(block)
            if source.read(1):
                raise ValueError("Unexpected trailing update bytes")
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected:
            raise ValueError("The update package checksum changed")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def run(*args):
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive"},
    )
    try:
        output, errors = process.communicate(timeout=600)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=5)
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, args, output, errors)
    return output.strip()


def check_package(path, target, previous):
    fields = run(
        "/usr/bin/dpkg-deb",
        "--field",
        str(path),
        "Package",
        "Version",
        "Architecture",
        "X-AI-Station-Desktop-Protocol",
    )
    actual = dict(line.split(": ", 1) for line in fields.splitlines())
    if actual != target["package"]:
        raise ValueError("The transferred package metadata differs from its accepted identity")
    if (
        previous != target
        and subprocess.run(
            [
                "/usr/bin/dpkg",
                "--compare-versions",
                target["package"]["Version"],
                "gt",
                previous["package"]["Version"],
            ],
            check=False,
            timeout=30,
            env={"PATH": "/usr/bin:/bin"},
        ).returncode
        != 0
    ):
        raise ValueError("Automatic package downgrades or unordered replacements are not allowed")


def backup_database(root, uid, operation):
    path = root / "data/db/ai-station.sqlite"
    if root.exists() or root.is_symlink():
        for folder in [HOME / ".local", HOME / ".local/share", root]:
            directory(folder, uid, private=True)
    for folder in [root / "data", path.parent]:
        if folder.exists() or folder.is_symlink():
            directory(folder, uid, private=True)
    if not path.exists() and not path.is_symlink():
        return False
    regular(path, uid, private=True)
    backup = STORE / (operation + ".sqlite")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
        if source.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Inspect the saved database before updating")
        active = source.execute(
            "SELECT count(*) FROM runs WHERE status NOT IN (?,?,?,?)", TERMINAL
        ).fetchone()[0]
        if active:
            raise RuntimeError("Saved work is still active; finish or stop it before updating")
        if backup.exists() or backup.is_symlink():
            regular(backup, 0, private=True)
            with sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True) as existing:
                if existing.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("Inspect the original pre-update backup before resuming")
            return True  # Keep the original pre-update backup on an exact-operation resume.
        backup.touch(mode=0o600, exist_ok=False)
        try:
            with sqlite3.connect(backup) as destination:
                source.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("The pre-update backup did not verify")
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
    return True


def installed(target):
    version = run(
        "/usr/bin/dpkg-query", "--show", "--showformat=${db:Status-Status}\n${Version}", "ai-station"
    )
    if version != "installed\n" + target["package"]["Version"]:
        raise ValueError("The package installation has not completed")
    # Only trusted installed source is imported, after the OS package completed.
    # The bundled desktop verifier checks every declared immutable application file.
    run(
        str(APP / "python/bin/python3"),
        "-IBS",
        "-c",
        "import sys;sys.path.insert(0,'/usr/lib/ai-station/scripts');import desktop;desktop.verify(desktop.ROOT,desktop.manifest(desktop.ROOT))",
    )


def update(source, previous, target, size, uid):
    accepted = plan(previous, target)
    previous, target = accepted["previous"], accepted["target"]
    directory(STORE.parent, 0)
    if not STORE.exists() and not STORE.is_symlink():
        STORE.mkdir(mode=0o700)
    directory(STORE, 0, private=True)
    operation = hashlib.sha256(canonical_json(accepted)).hexdigest()
    journal = STORE / "pending.json"
    root = HOME / ".local/share/ai-station-desktop"
    with ExitStack() as stack:
        stack.enter_context(locked(STORE / "update.lock", 0, create=True))
        current = identity(read_json(RECEIPT, 0))
        if current not in (previous, target):
            raise ValueError("The installed guest identity changed; no package was applied")
        # An existing, different pending update requires inspection, never adoption.
        pending = read_json(journal, 0) if journal.exists() or journal.is_symlink() else None
        if pending is not None and pending != {"operation": operation, "phase": "installing", **accepted}:
            raise ValueError("A different update is awaiting inspection")
        if PENDING_MARKER.exists() or PENDING_MARKER.is_symlink():
            if read_json(PENDING_MARKER, 0) != {"operation": operation}:
                raise ValueError("A different update marker requires inspection")
        for folder in [HOME / ".local", HOME / ".local/share", root]:
            if not folder.exists() and not folder.is_symlink():
                folder.mkdir(mode=0o700)
                if os.geteuid() == 0:
                    os.chown(folder, uid, -1)
            directory(folder, uid, private=True)
        stack.enter_context(locked(root / "desktop.lock", uid, create=True))
        runtime = root / "data/runtime"
        if runtime.exists() or runtime.is_symlink():
            directory(root / "data", uid, private=True)
            directory(runtime, uid, private=True)
            stack.enter_context(locked(runtime / "launcher.lock", uid, create=True))
        stage = STORE / (operation + ".deb.part")
        if stage.exists() or stage.is_symlink():
            regular(stage, 0, private=True)
            stage.unlink()  # Only this exact closed-operation transfer, never application files.
        receive(source, stage, target["package_sha256"], size)
        try:
            check_package(stage, target, previous)
            backed_up = backup_database(root, uid, operation)
            atomic_json(journal, {"operation": operation, "phase": "installing", **accepted})
            atomic_json(PENDING_MARKER, {"operation": operation})
            if current != target:
                run("/usr/bin/dpkg", "--install", str(stage))
            installed(target)
            atomic_json(RECEIPT, target)
            atomic_json(
                STORE / (operation + ".json"), {"operation": operation, "phase": "complete", **accepted}
            )
            journal.unlink()
            PENDING_MARKER.unlink()
            return {"status": "updated", "backup_available": backed_up, "data_preserved": True}
        finally:
            stage.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution")
    args = parser.parse_args()
    uid = assert_host(args.distribution)
    os.umask(0o077)

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    source = sys.stdin.buffer
    header = source.readline(16385)
    if len(header) > 16384 or not header.endswith(b"\n"):
        raise ValueError("Invalid bounded update header")
    value = json.loads(header, object_pairs_hook=strict_object)
    if not isinstance(value, dict) or set(value) != {"previous", "target", "package_bytes"}:
        raise ValueError("Invalid update request")
    print(
        json.dumps(update(source, value["previous"], value["target"], value["package_bytes"], uid)),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, sqlite3.Error, KeyboardInterrupt):
        # Input/OS details may contain local names. Preserve private journal evidence.
        raise SystemExit(
            "Update did not complete. Existing data and any pre-update backup were preserved; inspect this installation."
        ) from None
