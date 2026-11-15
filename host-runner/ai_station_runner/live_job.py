"""Owned live-session supervisor; model children inherit its group and memory scope."""

import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path

from ai_station_runner import live_environment
from ai_station_runner.environment_files import read_json
from ai_station_runner.live_broker import LiveBroker
from ai_station_runner.live_contract import RAM_MIB, LiveRequest, reference_snapshot
from ai_station_runner.live_ipc import read_async
from ai_station_runner.memory_scope import require_scope
from ai_station_runner.runtime_install import atomic_json
from ai_station_runner.speech_environment import offline_environment


async def run(body, root, folder, secret):
    from ai_station_runner import live_portrait_environment

    policy = live_portrait_environment if body.mode == "portrait" else live_environment
    selected = policy.resolve_public(root, body.managed_runtime.model_dump())
    live_environment.model_paths(
        root, selected["environment"] / "models", live_environment.recipe(), verify_weights=True
    )
    if body.mode == "portrait":
        policy.model_paths(
            root, selected["portrait_environment"] / "models", policy.recipe(), verify_weights=True
        )
    environment = selected["environment"]
    children, descriptors = [], []

    async def child(kind, reference, gpu):
        fd = reference_snapshot(root, reference)
        descriptors.append(fd)
        request = {"parent_pid": os.getpid(), "reference_fd": fd, "reference_sha256": reference.sha256}
        if kind == "face" and body.mode == "portrait":
            request.update(
                face_detector=str(selected["face_detector"]),
                portrait_sdk=str(selected["portrait_sdk"]),
                portrait_models={
                    k: str(v)
                    for k, v in selected.items()
                    if k.startswith("portrait_") and k not in {"portrait_sdk", "portrait_environment"}
                },
            )
            argv = [str(selected["python"]), "-B", "-m", "ai_station_runner.live_portrait_job"]
        elif kind == "face":
            request.update(
                {key: str(selected[key]) for key in ("face_detector", "face_recognizer", "face_swapper")}
            )
            argv = [str(selected["python"]), "-B", "-m", "ai_station_runner.live_face_job"]
        else:
            request.update(runtime_root=str(environment), seed=body.seed)
            argv = [str(selected["python"]), "-B", str(environment / "integration/bridge.py")]
        request_path = folder / (kind + "-request.json")
        atomic_json(folder, request_path.name, request)
        env = {
            **offline_environment(environment),
            "CUDA_VISIBLE_DEVICES": str(gpu),
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "MODELSCOPE_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NUMBA_CACHE_DIR": str(environment / "cache/numba"),
            "OMP_NUM_THREADS": "2",
            "OPENCV_IO_MAX_IMAGE_PIXELS": str(20_000_000),
            **({"PYTHONPATH": str(Path(__file__).resolve().parent.parent)} if kind == "face" else {}),
        }
        process = await asyncio.create_subprocess_exec(
            *argv,
            str(request_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
            cwd=environment,
            env=env,
            pass_fds=(fd,),
        )
        children.append(process)
        ready = await asyncio.wait_for(
            read_async(process.stdout), min(120, max(1, body.deadline_at - time.time()))
        )
        if ready[:1] != b"J" or json.loads(ready[1:]).get("ready") is not True:
            raise ValueError("Live inference worker did not become ready")
        return process

    try:
        gpu = iter(body.gpus)
        specs = []
        if body.image:
            specs.append(("face", body.image, next(gpu)))
        if body.voice:
            specs.append(("voice", body.voice, next(gpu)))
        processes = await asyncio.gather(*(child(*spec) for spec in specs))
        workers = {spec[0]: process for spec, process in zip(specs, processes, strict=True)}
        broker = LiveBroker(
            **workers,
            secret=secret,
            deadline_at=body.deadline_at,
            statistics=lambda value: print(json.dumps({"live_statistics": value}), flush=True),
        )
        serving = asyncio.create_task(broker.serve(folder / "stream.sock"))
        # Socket binding must complete before publishing native readiness.
        for _ in range(100):
            if (folder / "stream.sock").exists():
                break
            if serving.done():
                await serving
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("Live stream could not bind its private socket")
        print(
            json.dumps({"live_ready": True, "face": bool(body.image), "voice": bool(body.voice)}), flush=True
        )
        exited = [asyncio.create_task(p.wait()) for p in children]
        try:
            done, _ = await asyncio.wait([serving, *exited], return_when=asyncio.FIRST_COMPLETED)
            if serving not in done:
                raise RuntimeError("A live inference process exited unexpectedly")
            await serving
        finally:
            serving.cancel()
            for task in exited:
                task.cancel()
        if broker.error:
            print(json.dumps({"live_failure": {"reason": broker.error}}), flush=True)
            raise RuntimeError("Live stream stopped after a transport or inference failure: " + broker.error)
        # Closed capture is interrupted, never transparently restarted by recovery.
        print(json.dumps({"live_disconnected": True, **broker.counts}), flush=True)
        return 75
    finally:
        for process in children:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
        for process in children:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), 3)
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        for fd in descriptors:
            os.close(fd)
        (folder / "stream.sock").unlink(missing_ok=True)


def main():
    request = Path(sys.argv[1])
    saved = read_json(request)
    root = Path(saved["data_root"]).resolve(strict=True)
    body = LiveRequest.model_validate(saved["request"])
    folder = root / "runtime/live-sessions" / str(body.run_id)
    if request != folder / "request.json" or request.resolve() != request:
        raise ValueError("Live session must use its direct owned request")
    if not 0 < body.deadline_at - time.time() <= 3600:
        raise ValueError("Live session deadline has expired or changed")
    require_scope(str(body.run_id), RAM_MIB)
    sys.exit(asyncio.run(run(body, root, folder, saved["stream_secret"])))


if __name__ == "__main__":
    main()
