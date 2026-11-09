"""Independent native owner for one exact administrator-approved desktop update."""

import argparse
import fcntl
import json
import os
import subprocess
import time

import desktop
import desktop_linux_update as linux
import desktop_versions as versions
from ai_station_runner.desktop_update_channel import command
from desktop_release_download import download
from desktop_update_authority import authority
from desktop_update_owner import lock_file
from desktop_upgrade_image import write

PHASES = {
    "queued",
    "downloading",
    "preparing",
    "ready",
    "apply_requested",
    "applying",
    "applied",
    "failed",
    "canceled",
    "inspection_required",
}


def folder(root, run_id):
    command({"action": "updates.inspect", "run_id": run_id})
    versions.directory(root)
    if root.stat().st_mode & 0o077:
        raise ValueError("Desktop updates require private native installation storage")
    parent = root / "desktop-updates"
    parent.mkdir(mode=0o700, exist_ok=True)
    if versions.directory(parent).st_mode & 0o077:
        raise ValueError("Desktop update journals must remain private")
    path = parent / run_id
    path.mkdir(mode=0o700, exist_ok=True)
    if versions.directory(path).st_mode & 0o077:
        raise ValueError("Desktop update journals must remain private")
    return path


def read(path):
    value = json.loads(versions.read_private(path, 16384))
    if not isinstance(value, dict):
        raise ValueError("The native update journal needs inspection")
    return value


def request(root, run_id):
    saved = read(folder(root, run_id) / "request.json")
    if (
        set(saved) != {"schema", "run_id", "request", "previous", "namespace_sha256"}
        or saved.get("schema") != 1
        or saved.get("run_id") != run_id
    ):
        raise ValueError("The native update request changed")
    command({"action": "updates.prepare", "run_id": run_id, "request": saved["request"]})
    versions.package_identity(saved["previous"])
    if saved["namespace_sha256"] != versions.namespace(root / "desktop.env")[1]:
        raise ValueError("The native update data namespace changed")
    return saved


def state(root, run_id):
    saved = read(folder(root, run_id) / "state.json")
    if saved.get("run_id") != run_id or saved.get("phase") not in PHASES:
        raise ValueError("The native update status needs inspection")
    return saved


def publish(root, run_id, phase, **values):
    if phase not in PHASES:
        raise ValueError("Invalid native update phase")
    previous = state(root, run_id)
    write(folder(root, run_id) / "state.json", previous | values | {"phase": phase})


class DesktopUpdates:
    def __init__(self, root, installed, value):
        linux.compatible(value)
        self.root, self.installed, self.value = root, installed, value

    def inspect(self, run_id):
        saved = request(self.root, run_id)
        result = state(self.root, run_id)
        phase = result["phase"]
        if phase in {"applied", "applying", "inspection_required"}:
            from desktop_update_recovery import completed, operation

            current = versions.load(self.root)
            if (
                current["phase"] == "ready"
                and current["package"] == result.get("target")
                and current["package"] == versions.package_identity(self.value)
                and current["namespace_sha256"] == saved["namespace_sha256"]
                and completed(self.root, operation(self.root, run_id))
            ):
                phase = "succeeded"
        return {
            "run_id": run_id,
            "phase": phase,
            "request": saved["request"],
            **{
                key: result[key]
                for key in ("downloaded_bytes", "size_bytes", "target", "error")
                if key in result
            },
        }

    def handle(self, value):
        value = command(value)
        action = value["action"]
        if action == "updates.capabilities":
            return {"installed": True, "platform": "linux-amd64", "version": self.value["version"]}
        run_id = value["run_id"]
        if action == "updates.inspect":
            return self.inspect(run_id)
        if action == "updates.prepare":
            proof = authority(self.root, run_id, expected=value["request"])
            if proof["canceled"]:
                raise ValueError("The desktop update was canceled")
            if (
                proof["request"]["platform"] != "linux-amd64"
                or proof["request"]["current_version"] != self.value["version"]
            ):
                raise ValueError("The update does not match this installed desktop")
            path = folder(self.root, run_id)
            expected = {
                "schema": 1,
                "run_id": run_id,
                "request": proof["request"],
                "previous": versions.package_identity(self.value),
                "namespace_sha256": proof["namespace_sha256"],
            }
            record = path / "request.json"
            if record.exists() or record.is_symlink():
                if request(self.root, run_id) != expected:
                    raise ValueError("The native update was prepared for different input")
                return self.inspect(run_id)  # Never repeat an uncertain native dispatch.
            desktop.verify(self.installed, self.value)
            write(record, expected)
            write(path / "state.json", {"run_id": run_id, "phase": "queued"})
            log = path / "native.log"
            descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                subprocess.Popen(
                    [
                        str(self.installed / "python/bin/python3"),
                        "-I",
                        str(self.installed / "scripts/desktop_auto_update.py"),
                        "--run-id",
                        run_id,
                    ],
                    env=desktop.launch_environment(),
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=descriptor,
                    stderr=descriptor,
                    close_fds=True,
                )
            except OSError:
                publish(
                    self.root,
                    run_id,
                    "failed",
                    error="The native update helper could not start. Your station was not changed.",
                )
                raise
            finally:
                os.close(descriptor)
            return self.inspect(run_id)
        saved = request(self.root, run_id)
        if action == "updates.apply":
            authority(self.root, run_id, expected=saved["request"], idle=True)
            stage = state(self.root, run_id)["phase"]
            if stage == "ready":
                publish(self.root, run_id, "apply_requested")
            elif stage != "apply_requested":
                raise ValueError("The native package is not ready for activation")
        elif action == "updates.cancel":
            if not authority(self.root, run_id, expected=saved["request"])["canceled"]:
                raise ValueError("Persist the update cancellation before stopping its transfer")
            if state(self.root, run_id)["phase"] not in {"queued", "downloading", "preparing", "ready"}:
                raise ValueError("The update has reached activation; inspect it before canceling")
            publish(self.root, run_id, "canceled")
        return self.inspect(run_id)


def execute(root, run_id):
    path = folder(root, run_id)
    saved = request(root, run_id)
    lock = lock_file(path, "helper.lock", create=True)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # Another owned helper is already preparing this exact request.
        if state(root, run_id)["phase"] != "queued":
            return  # Recovery inspects the existing stage; never redispatch installation.
        last = 0.0

        def check(force=False):
            nonlocal last
            if not force and time.monotonic() - last < 0.5:
                return
            if (
                authority(root, run_id, expected=saved["request"])["canceled"]
                or state(root, run_id)["phase"] == "canceled"
            ):
                raise InterruptedError("The update was canceled before activation")
            last = time.monotonic()

        def progress(done, total):
            if time.monotonic() - progress.last > 1 or done == total:
                publish(root, run_id, "downloading", downloaded_bytes=done, size_bytes=total)
                progress.last = time.monotonic()

        progress.last = 0
        try:
            check(True)
            publish(root, run_id, "downloading")
            coordinates = saved["request"]
            package, snapshot = download(
                root,
                coordinates["release_id"],
                coordinates["fingerprint"],
                coordinates["current_version"],
                coordinates["platform"],
                check=check,
                progress=progress,
            )
            publish(root, run_id, "preparing")
            installed, target = linux.retain_package(root, package, snapshot, check=check)
            check(True)
            publish(root, run_id, "ready", target=versions.package_identity(target))
            deadline = time.monotonic() + 1800
            while state(root, run_id)["phase"] != "apply_requested":
                check()
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        "The station did not become idle in time. Your version was not changed."
                    )
                time.sleep(0.5)

            def consent(previous, candidate):
                if previous != saved["previous"] or candidate != versions.package_identity(target):
                    raise ValueError("The update source or target changed before activation")
                authority(root, run_id, expected=saved["request"], idle=True)
                from desktop_update_recovery import begin

                begin(root, run_id)
                publish(root, run_id, "applying")
                return True  # The specific release was approved by the original app action.

            engine = linux.attested_engine(root, desktop.ROOT)
            publish(root, run_id, "apply_requested", engine=list(engine.identity))
            if not linux.apply(root, installed, target, run_id, consent=consent, engine=engine):
                raise RuntimeError("The native update was not activated")
            publish(root, run_id, "applied")
            subprocess.Popen(
                [
                    str(installed / "python/bin/python3"),
                    "-I",
                    str(installed / "scripts/desktop.py"),
                    "--console",
                    "--background",
                ],
                env=desktop.launch_environment(),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except InterruptedError:
            publish(root, run_id, "canceled")
        except Exception:
            uncertain = state(root, run_id)["phase"] in {"applying", "applied"}
            publish(
                root,
                run_id,
                "inspection_required" if uncertain else "failed",
                error=(
                    "The update needs native inspection. Your saved data and previous package were retained."
                    if uncertain
                    else "The update could not be prepared. Your current version was not changed."
                ),
            )
            raise
    finally:
        os.close(lock)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    current = desktop.manifest(desktop.ROOT)
    linux.compatible(current)
    execute(desktop.state_root(), args.run_id)
