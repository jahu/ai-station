"""Explicit opt-in real image acceptance through API, worker and private Host Runner.

Existing models only; downloading is disabled by the photo adapter. Results and
logs remain in a uniquely created temporary directory for human inspection.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    if os.environ.get("AI_STATION_REAL_GPU_TESTS") != "1":
        raise SystemExit("Set AI_STATION_REAL_GPU_TESTS=1 to explicitly allow real GPU inference")
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--gpu", default="auto")
    parser.add_argument("--modes", default="qwen,juggernaut,edit,recompose-one,recompose-many,upscale")
    parser.add_argument(
        "--upscale-result", action="store_true", help="Verify generation/edit followed by Upscale"
    )
    args = parser.parse_args()
    requested = args.modes.split(",")
    if set(requested) - {"qwen", "juggernaut", "edit", "recompose-one", "recompose-many", "upscale"}:
        raise SystemExit("Unknown smoke mode")
    script = Path(os.environ["AI_STATION_PHOTO_SCRIPT"]).resolve(strict=True)
    python = Path(os.environ["AI_STATION_PHOTO_PYTHON"]).expanduser().absolute()
    if not python.is_file():
        raise SystemExit("Configured photo Python does not exist")
    original_hash = hashlib.sha256(script.read_bytes()).hexdigest()
    root = Path(tempfile.mkdtemp(prefix="ai-station-real-images-"))
    os.environ.update(
        {
            "AI_STATION_DATA_DIR": str(root / "data"),
            "AI_STATION_DATA_HOST_PATH": str(root / "data"),
            "AI_STATION_DATABASE_URL": "",
            "AI_STATION_RUNNER_SOCKET": str(root / "runner/runner.sock"),
            "AI_STATION_PHOTO_SCRIPT": str(script),
            "AI_STATION_PHOTO_PYTHON": str(python),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    from app.api import app
    from app.config import clear_settings_cache
    from app.db import migrate, reset_engine, session_factory
    from app.engine import tick
    from app.runner_client import RunnerClient
    from fastapi.testclient import TestClient
    from PIL import Image

    clear_settings_cache()
    reset_engine()
    migrate()
    results = []
    print("Acceptance artifacts:", root, flush=True)
    with (root / "runner.log").open("w") as log:
        runner = subprocess.Popen(
            [sys.executable, "-m", "ai_station_runner.main"],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=log,
            stderr=log,
        )
        try:
            client = RunnerClient(timeout=5)
            for _ in range(100):
                try:
                    client.health()
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Private runner did not start")
            hardware = client.hardware()
            devices = hardware.get("gpus", [])
            if args.gpu != "auto":
                devices = [gpu for gpu in devices if str(gpu["index"]) == args.gpu]
            devices = [
                gpu
                for gpu in devices
                if (gpu.get("memory_total_mib") or 0) - (gpu.get("memory_used_mib") or 0) >= 9000
            ]
            if not devices:
                raise RuntimeError(
                    "No selected GPU has at least 9000 MiB free; existing workloads were left untouched"
                )
            gpu = str(min(devices, key=lambda item: item.get("memory_used_mib") or 0)["index"])
            api = TestClient(app)
            sources = []
            for color in [(180, 70, 40), (40, 90, 160)]:
                source = root / f"input-{len(sources)}.png"
                Image.new("RGB", (256, 256), color).save(source)
                with source.open("rb") as handle:
                    response = api.post(
                        "/api/images/uploads", files={"file": (source.name, handle, "image/png")}
                    )
                response.raise_for_status()
                sources.append(response.json()["id"])
            for mode in requested:
                body = {
                    "mode": "t2i",
                    "backend": mode,
                    "prompt": "A red ceramic cup on a wooden table, natural daylight",
                    "width": 256,
                    "height": 256,
                    "steps": 2,
                    "gpu": gpu,
                }
                if mode == "edit":
                    body = {
                        "mode": "img2img",
                        "edit_prompt": "Make the image blue",
                        "input_artifact_ids": sources[:1],
                        "max_side": 256,
                        "steps": 2,
                        "gpu": gpu,
                    }
                elif mode.startswith("recompose"):
                    body.update(
                        mode="recompose",
                        backend="qwen",
                        input_artifact_ids=sources[:1] if mode == "recompose-one" else sources,
                    )
                elif mode == "upscale":
                    body = {"mode": "upscale", "input_artifact_ids": sources[:1], "gpu": gpu}
                if args.upscale_result and mode != "upscale":
                    body["upscale_result"] = True
                response = api.post("/api/images/runs", json=body)
                response.raise_for_status()
                run_id = response.json()["id"]
                print("START", mode, run_id, flush=True)
                started = time.monotonic()

                def execute():
                    while True:
                        with session_factory()() as session:
                            tick(session, "real-image-acceptance")
                        if not args.upscale_result:
                            return
                        chain = api.get(f"/api/images/runs/{run_id}/workflow").json()["steps"]
                        if chain[-1]["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
                            return
                        time.sleep(0.2)

                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    future = pool.submit(execute)
                    try:
                        future.result(timeout=args.timeout)
                    except concurrent.futures.TimeoutError:
                        chain = api.get(f"/api/images/runs/{run_id}/workflow").json()["steps"]
                        for pending in chain:
                            if pending["status"] not in {"succeeded", "failed", "canceled", "interrupted"}:
                                api.post(f"/api/runs/{pending['id']}/cancel").raise_for_status()
                        future.result(timeout=30)
                chain = api.get(f"/api/images/runs/{run_id}/workflow").json()["steps"]
                run = chain[-1]
                artifacts = api.get("/api/artifacts", params={"run_id": run["id"]}).json()
                result = {
                    "mode": mode,
                    "run_id": run_id,
                    "status": run["status"],
                    "seconds": round(time.monotonic() - started, 1),
                    "error": run["error_message"],
                    "artifacts": artifacts,
                    "steps": chain,
                }
                results.append(result)
                (root / "results.json").write_text(json.dumps(results, indent=2))
                print("RESULT", mode, run["status"], result["seconds"], run["error_message"], flush=True)
                if run["status"] == "succeeded":
                    assert len(artifacts) == 1 and artifacts[0]["type"] == "image"
                    if body.get("upscale_result"):
                        assert len(chain) == 2 and all(step["status"] == "succeeded" for step in chain)
                        original = api.get("/api/artifacts", params={"run_id": run_id}).json()[0]
                        assert artifacts[0]["parent_artifact_ids"] == [original["id"]]
                        assert artifacts[0]["metadata"]["width"] == original["metadata"]["width"] * 4
                        assert artifacts[0]["metadata"]["height"] == original["metadata"]["height"] * 4
                    with Image.open(root / "data" / artifacts[0]["relative_path"]) as output:
                        output.verify()
                else:
                    for name in ("stderr.log", "stdout.log"):
                        path = root / "data/runs" / run_id / name
                        if path.exists():
                            print(path.read_text(errors="replace")[-2000:], flush=True)
        finally:
            runner.terminate()
            try:
                runner.wait(timeout=15)
            except subprocess.TimeoutExpired:
                runner.kill()
                runner.wait()
            assert hashlib.sha256(script.read_bytes()).hexdigest() == original_hash
            reset_engine()
    print("Results preserved:", root, flush=True)
    if any(result["status"] != "succeeded" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
