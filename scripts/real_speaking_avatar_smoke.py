"""Explicitly opted-in local speech-to-avatar acceptance with isolated app storage."""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    if os.environ.get("AI_STATION_REAL_GPU_TESTS") != "1":
        raise SystemExit("Set AI_STATION_REAL_GPU_TESTS=1 to opt into real local media inference")
    parser = argparse.ArgumentParser()
    parser.add_argument("--portrait", required=True, type=Path)
    parser.add_argument("--voice", required=True, type=Path)
    parser.add_argument("--text", default="Cześć, to test AI Station.")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="ai-station-real-speaking-avatar-"))
    os.environ.update(
        AI_STATION_DATA_DIR=str(root / "data"),
        AI_STATION_DATA_HOST_PATH=str(root / "data"),
        AI_STATION_DATABASE_URL="",
        AI_STATION_RUNNER_SOCKET=str(root / "runner/runner.sock"),
    )
    from app.api import app
    from app.config import clear_settings_cache
    from app.db import migrate, reset_engine, session_factory
    from app.engine import tick
    from app.resources import active_locks
    from app.runner_client import RunnerClient
    from fastapi.testclient import TestClient

    clear_settings_cache()
    reset_engine()
    migrate()
    print("Acceptance data:", root, flush=True)
    with (root / "runner.log").open("w") as log:
        runner = subprocess.Popen(
            [sys.executable, "-m", "ai_station_runner.main"],
            env=os.environ.copy(),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            host = RunnerClient(timeout=5)
            for _ in range(100):
                try:
                    host.health()
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Private Runner did not become ready")
            free = [
                gpu
                for gpu in host.hardware().get("gpus", [])
                if (gpu.get("memory_total_mib") or 0) - (gpu.get("memory_used_mib") or 0) >= 9000
            ]
            if not free:
                raise RuntimeError("No GPU has 9000 MiB free; existing workloads left untouched")
            gpu = str(min(free, key=lambda item: item.get("memory_used_mib") or 0)["index"])
            with TestClient(app) as client:
                with args.portrait.open("rb") as portrait, args.voice.open("rb") as voice:
                    image = client.post("/api/images/uploads", files={"file": (args.portrait.name, portrait)})
                    audio = client.post("/api/audio/uploads", files={"file": (args.voice.name, voice)})
                image.raise_for_status()
                audio.raise_for_status()
                response = client.post(
                    "/api/avatars/runs",
                    json={
                        "image_artifact_id": image.json()["id"],
                        "audio_artifact_id": audio.json()["id"],
                        "speech_text": args.text,
                        "size": 256,
                        "frames": 17,
                        "steps": 4,
                        "gpu": gpu,
                    },
                )
                response.raise_for_status()
                run_id = response.json()["id"]
                route = f"/api/avatars/runs/{run_id}/workflow"

                def execute():
                    while True:
                        with session_factory()() as session:
                            tick(session, "real-speaking-avatar")
                        chain = client.get(route).json()["steps"]
                        if chain[-1]["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
                            return
                        time.sleep(0.2)

                started = time.monotonic()
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    future = pool.submit(execute)
                    try:
                        future.result(timeout=args.timeout)
                    except concurrent.futures.TimeoutError:
                        for pending in client.get(route).json()["steps"]:
                            if pending["status"] not in {"succeeded", "failed", "canceled", "interrupted"}:
                                client.post(f"/api/runs/{pending['id']}/cancel").raise_for_status()
                        future.result(timeout=30)
                chain = client.get(route).json()["steps"]
                artifacts = {
                    step["id"]: client.get("/api/artifacts", params={"run_id": step["id"]}).json()
                    for step in chain
                }
                (root / "results.json").write_text(
                    json.dumps(
                        {
                            "steps": chain,
                            "artifacts": artifacts,
                            "seconds": round(time.monotonic() - started, 1),
                        },
                        indent=2,
                    )
                )
                assert len(chain) == 2 and all(step["status"] == "succeeded" for step in chain), chain
                speech, video = [artifacts[step["id"]][0] for step in chain]
                assert speech["parent_artifact_ids"] == [audio.json()["id"]]
                assert video["parent_artifact_ids"] == [image.json()["id"], speech["id"]]
                assert client.get(f"/api/artifacts/{video['id']}/file").headers["content-type"] == "video/mp4"
                with session_factory()() as session:
                    assert not active_locks(session)
                print(
                    "PASS: real speech and avatar Runs, both artifacts, lineage and released GPU", flush=True
                )
        finally:
            runner.terminate()
            try:
                runner.wait(timeout=15)
            except subprocess.TimeoutExpired:
                runner.kill()
                runner.wait()
            reset_engine()


if __name__ == "__main__":
    main()
