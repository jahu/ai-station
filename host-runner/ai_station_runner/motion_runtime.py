"""Typed CPU renderer launch, observation and owned restart semantics."""

import fcntl
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_station_runner.config import get_settings
from ai_station_runner.memory_scope import available, scope_environment, scope_prefix
from ai_station_runner.motion_assets import request_digest
from ai_station_runner.motion_contract import RAM_MIB, SUPERVISOR_RAM_MIB
from ai_station_runner.motion_image import image
from ai_station_runner.motion_installation import observation
from ai_station_runner.motion_owner import directory, load, save
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.security import resolve_child

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="motion-readiness")
_lock = threading.Lock()
_probe = None


def capabilities():
    global _probe
    base = {
        "name": "Hyperframes · CPU",
        "ram_mib": RAM_MIB,
        "max_seconds": 600,
        "fps": 30,
        "canvases": [
            {"width": 1080, "height": 1920},
            {"width": 1920, "height": 1080},
            {"width": 1080, "height": 1080},
        ],
        "gpu": "none",
    }
    try:
        if not available():
            raise ValueError("Motion rendering needs an owned user memory scope")
        settings = get_settings()
        key = (str(settings.host_data_dir()), settings.motion_image)
        with _lock:
            if _probe is None or _probe[0] != key or (_probe[1].done() and time.monotonic() - _probe[2] > 30):
                _probe = (key, _pool.submit(image, settings), time.monotonic())
            task = _probe[1]
        if not task.done():
            return {
                **base,
                "available": False,
                "readiness": "checking",
                "reason": "Checking the isolated motion renderer",
            }
        installed = task.result()
        return {**base, "available": True, "readiness": "ready", "observation": observation(installed)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {
            **base,
            "available": False,
            "readiness": "unavailable",
            "reason": "Prepare the isolated Hyperframes renderer in Studio",
        }


def start(manager, body):
    root, rid = manager.data_dir.resolve(), str(body.run_id)
    folder = directory(root, rid)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    request = body.model_dump(mode="json")
    existing = False
    with (folder / "launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = folder / "request.json"
        if receipt.exists() or receipt.is_symlink():
            saved = load(root, rid)
            if saved["request"] != request:
                raise ValueError("Motion launch identity changed; inspect existing work")
            existing = True
        else:
            if (folder / "cancel.json").exists():
                raise InterruptedError("Motion render was canceled before dispatch")
            # Never hold a container ownership lock while entering ProcessManager.
            try:
                manager.inspect(rid)
            except ProcessNotOwned:
                pass
            else:
                raise ValueError("Run already owns a process")
            if not available():
                raise ValueError("Motion rendering needs an owned user memory scope")
            installed = image(get_settings())
            now = time.time()
            if body.observation != observation(installed) or not now < body.deadline_at <= now + 3600:
                raise ValueError("Motion implementation or bounded deadline changed")
            if os.getuid() == 0:
                raise ValueError("Run the native motion supervisor as a regular user")
            for source in body.sources:
                path = resolve_child(root, source.relative_path)
                if (
                    not source.relative_path.startswith("artifacts/")
                    or path != root / source.relative_path
                    or not path.is_file()
                    or path.stat().st_size != source.size_bytes
                ):
                    raise ValueError("Motion media observation changed")
            output = resolve_child(root, f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.mp4")
            if output.exists() or output.is_symlink():
                raise ValueError("Inspect existing motion output rather than overwrite it")
            with (folder / "container.lock").open("a") as owned_lock:
                fcntl.flock(owned_lock, fcntl.LOCK_EX)
                if (folder / "cancel.json").exists():
                    raise InterruptedError("Motion render was canceled before dispatch")
                save(
                    receipt,
                    {
                        "request": request,
                        "digest": request_digest(body),
                        "image": installed["image_id"],
                        "recipe": installed["recipe_sha256"],
                        "connection": installed["connection"],
                        "user": f"{os.getuid()}:{os.getgid()}",
                    },
                )
    if existing:
        try:
            owned = manager.inspect(rid)
        except ProcessNotOwned as exc:
            raise ValueError("Inspect the existing motion launch before retrying") from exc
        if owned.get("executor") != "motion_render":
            raise ValueError("Run belongs to another executor")
        return owned
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "DOCKER_CONFIG"}}
    env.update(
        scope_environment(),
        CUDA_VISIBLE_DEVICES="",
        NVIDIA_VISIBLE_DEVICES="none",
        PYTHONUNBUFFERED="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(Path(__file__).resolve().parent.parent),
        AI_STATION_DATA_HOST_PATH=str(root),
        AI_STATION_DATA_DIR=str(root),
    )
    return manager.start(
        run_id=rid,
        executor="motion_render",
        cwd=root,
        argv=scope_prefix(rid, SUPERVISOR_RAM_MIB)
        + [sys.executable, "-m", "ai_station_runner.motion_job", rid],
        env=env,
        deadline_at=body.deadline_at,
    )
