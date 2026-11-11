"""Native supervisor for one isolated, exactly owned CPU motion container."""

import fcntl
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys

from ai_station_runner.config import get_settings
from ai_station_runner.memory_scope import require_scope
from ai_station_runner.motion_assets import asset_names, request_digest
from ai_station_runner.motion_contract import SUPERVISOR_RAM_MIB, MotionRequest
from ai_station_runner.motion_docker import docker, environment
from ai_station_runner.motion_owner import create, directory, inspect_owned, load, save, stop
from ai_station_runner.security import resolve_child


def copy_source(root, source, target):
    path = resolve_child(root, source.relative_path)
    if not source.relative_path.startswith("artifacts/") or path != root / source.relative_path:
        raise ValueError("Motion sources must be canonical app-owned artifacts")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as incoming, target.open("xb") as outgoing:
        before = os.fstat(incoming.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != source.size_bytes:
            raise ValueError("Motion source is not the recorded regular file")
        digest, size = hashlib.sha256(), 0
        for block in iter(lambda: incoming.read(1024 * 1024), b""):
            size += len(block)
            if size > source.size_bytes:
                raise ValueError("Motion source grew during inspection")
            digest.update(block)
            outgoing.write(block)
        after = os.fstat(incoming.fileno())
        current = path.stat(follow_symlinks=False)
        if (
            digest.hexdigest() != source.sha256
            or size != source.size_bytes
            or any(
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
                for item in (after, current)
            )
        ):
            raise ValueError("Motion source changed during inspection")


def read_report(path, request):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 1 <= info.st_size <= 64000:
            raise ValueError("Motion report is not a bounded regular file")
        report = json.loads(handle.read(64001))
    if (
        not isinstance(report, dict)
        or report.get("verified") is not True
        or report.get("run_id") != str(request.run_id)
        or report.get("request_sha256") != request_digest(request)
        or report.get("observation") != request.observation
        or report.get("frames") != request.composition.frames
        or (report.get("width"), report.get("height"))
        != (request.composition.width, request.composition.height)
        or report.get("fps") != 30
        or report.get("has_audio") is not bool(request.audio_artifact_id)
    ):
        raise ValueError("Motion report does not match the owned request")
    return report


def collect(source, target):
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as incoming:
        before = os.fstat(incoming.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 1 <= before.st_size <= 2 * 1024**3:
            raise ValueError("Motion output is not a bounded regular file")
        with target.open("xb") as outgoing:
            size = 0
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                size += len(block)
                if size > before.st_size:
                    raise ValueError("Motion output changed during collection")
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        after = os.fstat(incoming.fileno())
        if size != before.st_size or (before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Motion output changed during collection")


def render(run_id):
    root = get_settings().host_data_dir().resolve()
    saved = load(root, run_id)
    request = MotionRequest.model_validate(saved["request"])
    scope = require_scope(str(request.run_id), SUPERVISOR_RAM_MIB)
    folder = directory(root, run_id)
    work = folder / "work"
    work.mkdir(mode=0o700)
    assets = work / "project/assets"
    assets.mkdir(mode=0o700, parents=True)
    names = asset_names(request)
    try:
        for source in request.sources:
            copy_source(root, source, work / "project" / names[str(source.artifact_id)])
        save(work / "request.json", saved["request"])
        cid = create(root, saved)
        with (folder / "container.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (folder / "cancel.json").exists():
                raise InterruptedError("Motion render canceled before container start")
            inspect_owned(root, saved, cid)
            docker(["start", cid], bound=saved["connection"])
        log = subprocess.run(
            ["docker", "--host", saved["connection"]["host"], "logs", "--follow", cid],
            env=environment(),
            timeout=3450,
        )
        item = inspect_owned(root, saved, cid)
        if log.returncode or item is None or item["State"]["Running"] or item["State"]["ExitCode"] != 0:
            raise ValueError("Motion container did not complete successfully; inspect its Run logs")
        report = read_report(work / "output/report.json", request)
        if not stop(root, run_id):
            raise ValueError("Motion container cleanup requires inspection")
        with (folder / "container.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (folder / "cancel.json").exists():
                raise InterruptedError("Motion render canceled before publication")
            rid = str(request.run_id)
            output = resolve_child(root, f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.mp4")
            if output.exists() or output.is_symlink():
                raise ValueError("Inspect existing motion output rather than overwrite it")
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(rid + ".partial.mp4")
            collect(work / "output/render.mp4", temporary)
            report.update(image_id=saved["image"], recipe_sha256=saved["recipe"], supervisor_bounds=scope)
            save(output.with_suffix(".json"), report)
            os.replace(temporary, output)
        print("motion.export.verified", flush=True)
    finally:
        if stop(root, run_id) and work.resolve() == work:
            shutil.rmtree(work)


if __name__ == "__main__":

    def canceled(_signal, _frame):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, canceled)
    render(str(__import__("uuid").UUID(sys.argv[1])))
