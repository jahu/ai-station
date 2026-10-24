"""Host-only quiescence checks. No services or processes are stopped here."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

from .storage import RecoveryError, data_path, regular_file


def assert_no_containers(root: Path) -> None:
    """Inspect mounts, not project names that an accidentally changed env can hide."""
    try:
        listing = subprocess.run(
            ["docker", "ps", "--all", "--quiet"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        ids = listing.stdout.split()
        if not ids:
            return
        if len(ids) > 256:
            raise RecoveryError("Container inventory exceeds the recovery inspection bound")
        template = '{"State":{"Running":{{json .State.Running}},"Paused":{{json .State.Paused}},"Restarting":{{json .State.Restarting}}},"Mounts":{{json .Mounts}}}'
        inspected = subprocess.run(
            ["docker", "inspect", "--format", template, *ids],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if len(inspected.stdout.encode()) > 4 * 1024 * 1024:
            raise RecoveryError("Container inventory exceeds the recovery inspection bound")
        # Request only state/mount metadata, never unrelated container secrets.
        containers = [json.loads(line) for line in inspected.stdout.splitlines() if line.strip()]
    except RecoveryError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RecoveryError("Docker inspection must succeed before offline recovery") from exc
    if len(containers) != len(ids):
        raise RecoveryError("The complete container inventory must be inspected before recovery")
    for container in containers:
        if not isinstance(container, dict) or not isinstance(container.get("State"), dict):
            raise RecoveryError("Container state must be confirmed before offline recovery")
        state = container["State"]
        if any(not isinstance(state.get(key), bool) for key in ("Running", "Paused", "Restarting")):
            raise RecoveryError("Container state must be confirmed before offline recovery")
        if not any(state.get(key) for key in ("Running", "Paused", "Restarting")):
            continue
        mounts = container.get("Mounts") or []
        if not isinstance(mounts, list):
            raise RecoveryError("Container mounts must be confirmed before offline recovery")
        for mount in mounts:
            if not isinstance(mount, dict):
                raise RecoveryError("Container mounts must be confirmed before offline recovery")
            if not mount.get("Source"):
                continue
            source = Path(mount["Source"]).resolve()
            if source == root or source in root.parents or root in source.parents:
                raise RecoveryError(
                    "Stop containers using this data directory, including owned models and previews"
                )


def assert_no_native_groups(root: Path) -> None:
    from ai_station_runner.processes import _group_alive

    journal = data_path(root, "runtime/processes.json", required=False)
    if not journal.exists():
        return
    if regular_file(journal).st_size > 16 * 1024 * 1024:
        raise RecoveryError("Native process inventory exceeds its recovery bound")
    try:
        records = json.loads(journal.read_bytes())
        if not isinstance(records, dict):
            raise ValueError("Invalid process inventory")
        for record in records.values():
            if not isinstance(record, dict) or not record.get("boot_id") or not record.get("start_ticks"):
                raise ValueError("Unconfirmed process identity")
            if _group_alive(record):
                raise RecoveryError("Stop the owned native workload before restoring its database")
    except RecoveryError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("Native process ownership must be inspected before recovery") from exc


def process_entries():
    return Path("/proc").iterdir()


def assert_no_database_users(root: Path) -> None:
    identities = set()
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = data_path(root, "db/ai-station.sqlite" + suffix, required=False)
        if path.exists():
            info = regular_file(path)
            identities.add((info.st_dev, info.st_ino))
    for process in process_entries():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            for descriptor in (process / "fd").iterdir():
                try:
                    info = descriptor.stat()
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if (info.st_dev, info.st_ino) in identities:
                    raise RecoveryError("An application database connection is still open")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            # Protected desktop/PAM processes are not SQLite executors in this
            # architecture. Owned Chromium jobs are covered by the preceding
            # container and native-group guards. Do not require stopping the
            # operator's desktop merely because its descriptors are private.
            try:
                if (process / "comm").read_text().strip() in {
                    "(sd-pam)",
                    "systemd",
                    "chrome",
                    "chromium",
                    "chromium-browser",
                }:
                    continue
            except (FileNotFoundError, ProcessLookupError):
                continue
            except OSError:
                pass
            raise RecoveryError(
                f"Open database users could not be confirmed for PID {process.name}; recovery stays offline"
            ) from exc


@contextmanager
def offline_guard(root: Path):
    """Cooperate with normal startup; no process/container is stopped by recovery."""
    root = root.resolve(strict=True)
    path = data_path(root, "runtime/launcher.lock", required=False)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_uid != os.getuid():
            raise RecoveryError("Recovery requires the ordinary user-owned launcher lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryError("Stop the AI Station supervisor before restoring its database") from exc
        assert_no_containers(root)
        assert_no_native_groups(root)
        assert_no_database_users(root)
        yield
    finally:
        os.close(fd)
