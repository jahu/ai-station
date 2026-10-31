"""Fixed CPU timeline operation with an owned process and private memory scope."""

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_station_runner.config import get_settings
from ai_station_runner.memory_scope import available, scope_environment, scope_prefix
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.security import resolve_child
from ai_station_runner.timeline_contract import RAM_MIB
from ai_station_runner.timeline_observation import observation

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="timeline-readiness")
_lock = threading.Lock()
_probe = {}


def installation():
    cfg = get_settings()
    configured = (cfg.mmaudio_python if cfg.mmaudio_enabled else "") or cfg.video_python
    if not configured:
        from ai_station_runner.effects_selection import selection as effects_selection

        effects = effects_selection(cfg) or {}
        if effects.get("managed"):
            configured = effects["mmaudio_python"]
    if not configured:
        from ai_station_runner.video_selection import selection

        managed = selection(cfg) or {}
        if managed.get("managed"):
            configured = managed["video_python"]
    if not configured:
        raise ValueError("Configure a CPU video Python with PyAV, NumPy and Pydantic v2")
    python = Path(configured).expanduser().absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Configured video Python is unavailable")
    if not available():
        raise ValueError("Timeline rendering needs an owned user memory scope")
    return python


def probe(python):
    result = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import av,numpy,pydantic; assert int(pydantic.VERSION.split('.')[0])==2; assert av.Codec('libx264','w').is_encoder; print('ready')",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        env={k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "LD_LIBRARY_PATH"}},
    )
    if result.returncode or result.stdout.strip() != "ready":
        raise ValueError("Video Python needs PyAV/libx264, NumPy and Pydantic v2")
    return True


def capabilities():
    base = {
        "name": "Timeline · CPU",
        "ram_mib": RAM_MIB,
        "max_seconds": 300,
        "max_clips": 16,
        "max_tracks": 16,
    }
    try:
        python = installation()
        signature = (str(python), python.stat().st_mtime_ns)
        with _lock:
            entry = _probe.get(signature)
            if entry is None or (entry[0].done() and time.monotonic() - entry[1] > 30):
                entry = (_pool.submit(probe, python), time.monotonic())
                _probe.clear()
                _probe[signature] = entry
        if not entry[0].done():
            return {
                **base,
                "available": False,
                "readiness": "checking",
                "reason": "Checking CPU timeline renderer",
            }
        entry[0].result()
        return {**base, "available": True, "readiness": "ready", "observation": observation()}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {
            **base,
            "available": False,
            "readiness": "unavailable",
            "reason": "Configure a CPU video Python with PyAV/libx264, NumPy, Pydantic v2 and an owned user memory scope",
        }


def start(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise PermissionError("Timeline rendering requires artifact read/write permissions")
    python = installation()
    root, rid = manager.data_dir.resolve(), str(body.run_id)
    launch = resolve_child(root, f"runs/{rid}/timeline-launch")
    if launch != root / f"runs/{rid}/timeline-launch":
        raise ValueError("Timeline launch traverses a symlink")
    receipt = launch / "request.json"
    record = {"request": body.model_dump(mode="json"), "python": str(python)}
    if launch.exists():
        if receipt.resolve() != receipt or not receipt.is_file() or json.loads(receipt.read_text()) != record:
            raise ValueError("Timeline launch identity changed; inspect existing work")
        try:
            owned = manager.inspect(rid)
        except ProcessNotOwned as exc:
            raise ValueError("Inspect an existing timeline launch before retrying") from exc
        if owned.get("executor") != "timeline_render":
            raise ValueError("Run belongs to another executor")
        return owned
    try:
        manager.inspect(rid)
    except ProcessNotOwned:
        pass
    else:
        raise ValueError("Run already owns a process")
    if body.deadline_at <= time.time() or body.observation != observation():
        raise ValueError("Timeline deadline or implementation changed")
    for source in body.sources:
        path = resolve_child(root, source.relative_path)
        if (
            not source.relative_path.startswith("artifacts/")
            or path != root / source.relative_path
            or not path.is_file()
            or path.stat().st_size != source.size_bytes
        ):
            raise ValueError("Timeline media observation changed")
        if not source.relative_path.endswith(".mp4" if source.kind == "video" else ".wav"):
            raise ValueError("Choose canonical timeline media")
    output = resolve_child(root, f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.mp4")
    if output.exists() or output.is_symlink():
        raise ValueError("Inspect existing timeline output instead of overwriting")
    launch.mkdir(mode=0o700, parents=True)
    with receipt.open("x") as handle:
        os.chmod(receipt, 0o600)
        json.dump(record, handle)
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "LD_LIBRARY_PATH"}}
    env.update(
        scope_environment(),
        CUDA_VISIBLE_DEVICES="",
        PYTHONUNBUFFERED="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(Path(__file__).parent.parent),
    )
    return manager.start(
        run_id=rid,
        executor="timeline_render",
        cwd=root,
        argv=scope_prefix(rid, RAM_MIB) + [str(python), "-m", "ai_station_runner.timeline_job", str(receipt)],
        env=env,
        deadline_at=body.deadline_at,
    )
