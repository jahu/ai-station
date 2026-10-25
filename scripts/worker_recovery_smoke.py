"""Opt-in actual CPU-container worker/Runner crash recovery; no inference or live data."""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def wait_for(probe, *, seconds=40):
    deadline = time.monotonic() + seconds
    while True:
        value = probe()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise TimeoutError("Owned recovery probe did not reach the required state")
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Already installed trusted Python executor image")
    parser.add_argument(
        "--failure-target",
        choices=["worker", "runner"],
        default="worker",
        help="Kill the disposable worker (default) or its isolated native Runner",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="New private evidence directory")
    args = parser.parse_args()
    if os.environ.get("AI_STATION_REAL_RECOVERY_TESTS") != "1":
        raise SystemExit("Set AI_STATION_REAL_RECOVERY_TESTS=1 to run the actual CPU container probe")
    if not re.fullmatch(r"ai-station-python:[A-Za-z0-9_.-]+", args.image):
        raise SystemExit("Choose an installed ai-station-python:<tag> accepted by the native executor")
    # Installation must be explicit. Inspect never pulls/builds a missing image.
    subprocess.run(["docker", "image", "inspect", args.image], check=True, stdout=subprocess.DEVNULL)
    evidence = args.output_dir.resolve()
    evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = Path(tempfile.mkdtemp(prefix="as-recovery-"))
    original_cwd = Path.cwd()
    # A private cwd prevents either component from loading the workstation .env.
    # Remove inherited application settings before importing any application code.
    env = {key: value for key, value in os.environ.items() if not key.startswith("AI_STATION_")}
    env.update(
        PYTHONPATH=str(ROOT / "backend") + ":" + str(ROOT / "host-runner"),
        AI_STATION_DATA_DIR=str(root / "data"),
        AI_STATION_DATA_HOST_PATH=str(root / "data"),
        AI_STATION_RUNNER_SOCKET=str(root / "socket" / "runner.sock"),
        AI_STATION_ALLOWED_ROOTS=str(root / "repository"),
        AI_STATION_PYTHON_IMAGE=args.image,
        AI_STATION_TAILNET_PRIVATE_DIR=str(root / "tailnet"),
        AI_STATION_TAILNET_BINARY_DIR=str(root / "tailnet-bin"),
        AI_STATION_LEASE_SECONDS="2",
        AI_STATION_HEARTBEAT_SECONDS="1",
        AI_STATION_WORKER_SLOTS="1",
        PYTHONUNBUFFERED="1",
    )
    for key in list(os.environ):
        if key.startswith("AI_STATION_"):
            del os.environ[key]
    os.environ.update(env)
    os.chdir(root)
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "host-runner")]
    from app.api import app
    from app.db import reset_engine, session_factory
    from app.engine import tick
    from app.models import Artifact, Run, RunEvent
    from app.python_execution import PERMISSIONS, enqueue_python
    from app.recovery import recover_stale
    from app.runner_client import RunnerClient, RunnerUnavailable
    from app.runs import request_cancel
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    processes = []
    jobs = []
    started = []
    results = []
    runner = RunnerClient(timeout=10)
    log = (evidence / "processes.log").open("x", encoding="utf-8")
    os.chmod(log.name, 0o600)
    completed = False
    image_id = None

    def launch(module, *, worker=False):
        command = [sys.executable, "-m", module]
        if worker:
            command = [
                sys.executable,
                "-c",
                "from app.db import session_factory;from app.engine import tick;"
                "s=session_factory()();tick(s,'crash-probe');s.close()",
            ]
        process = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log)
        processes.append(process)
        return process

    def native_ready():
        try:
            return runner.health()
        except RunnerUnavailable:
            return None

    def inspect_job(rid):
        return runner.inspect_process(rid)

    def recover(rid):
        with session_factory()() as session:
            recover_stale(session, runner)
            session.commit()
            row = session.get(Run, rid)
            return row.status

    try:
        repo = root / "repository"
        repo.mkdir()
        for command in (
            ["init", "-b", "develop"],
            ["config", "user.name", "Recovery acceptance"],
            ["config", "user.email", "recovery@example.invalid"],
        ):
            subprocess.run(["git", "-C", str(repo), *command], check=True, stdout=log, stderr=log)
        original = b"Original fixture, never edited by an agent.\n"
        (repo / "README.md").write_bytes(original)
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "Fixture"], check=True, stdout=log)
        index = (repo / ".git/index").read_bytes()
        native_process = launch("ai_station_runner.main")
        wait_for(native_ready)
        caps = runner.request("GET", "/v1/python/capabilities")
        assert caps["available"], "The installed image does not meet the trusted executor protocol"
        image_id = caps["image_id"]
        with TestClient(app) as client:
            response = client.post("/api/projects", json={"name": "Recovery fixture", "repo_path": str(repo)})
            assert response.status_code == 201, response.text
            project = response.json()
            response = client.post(
                f"/api/projects/{project['id']}/worktrees",
                json={"expected_updated_at": project["updated_at"]},
            )
            assert response.status_code == 202, response.text
            preparation = response.json()
            with session_factory()() as session:
                assert tick(session, "recovery-preparation") == preparation["id"]
            tree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
            assert client.get(f"/api/runs/{preparation['id']}").json()["status"] == "succeeded"
            for mode, duration in [("complete", 15), ("cancel", 60)]:
                code = (
                    "from pathlib import Path\nimport time\n"
                    "print('RECOVERY_PROBE_STARTED', flush=True)\n"
                    f"time.sleep({duration})\n"
                    "Path('result.csv').write_text('value\\n27\\n')\n"
                ).encode()
                entry = f"{mode}.py"
                source = root / "data" / tree["relative_path"] / entry
                source.write_bytes(code)
                with session_factory()() as session:
                    task = session.get(Run, preparation["id"]).task
                    row = enqueue_python(
                        session,
                        task,
                        {
                            "worktree_id": tree["id"],
                            "script_relative": entry,
                            "script_sha256": hashlib.sha256(code).hexdigest(),
                            "expected_outputs": ["result.csv"],
                            "maximum_runtime": 90,
                        },
                        permissions=list(PERMISSIONS),
                    )
                    rid = row.id
                    jobs.append(rid)
                    session.commit()
                worker = launch("", worker=True)

                def running():
                    with session_factory()() as session:
                        row = session.get(Run, rid)
                        if row.status == "failed":
                            raise AssertionError(row.error_message)
                        if row.status != "running" or not row.metadata_json.get("dispatch_attempted"):
                            return None
                    state = inspect_job(rid)
                    return (
                        state
                        if state.get("alive") and "RECOVERY_PROBE_STARTED" in state.get("stdout", "")
                        else None
                    )

                launched = wait_for(running)
                started.append(rid)
                assert worker.poll() is None
                if args.failure_target == "worker":
                    worker.send_signal(signal.SIGKILL)
                    worker.wait(timeout=10)
                    assert worker.returncode == -signal.SIGKILL
                else:
                    assert native_process.poll() is None
                    native_process.send_signal(signal.SIGKILL)
                    native_process.wait(timeout=10)
                    assert native_process.returncode == -signal.SIGKILL
                    # Wait for actual transport loss to finish the original tick;
                    # reconnecting too early would conceal the uncertain dispatch.
                    worker.wait(timeout=15)
                    assert worker.returncode == 0
                    with session_factory()() as session:
                        row = session.get(Run, rid)
                        assert row.status == "running" and row.metadata_json["dispatch_attempted"]
                        events = list(session.scalars(select(RunEvent).where(RunEvent.run_id == rid)))
                        assert any(event.event_type == "recovery.inspection_required" for event in events)
                    native_process = launch("ai_station_runner.main")
                    wait_for(native_ready)
                    adopted = inspect_job(rid)
                    assert adopted["alive"] and adopted["pid"] == launched["pid"]
                # No fake clock or rewritten lease: wait for the actual heartbeat
                # lease to expire, then run the ordinary recovery service.
                time.sleep(2.5)
                assert recover(rid) == "running"
                with session_factory()() as session:
                    events = list(session.scalars(select(RunEvent).where(RunEvent.run_id == rid)))
                    assert any(event.event_type == "recovery.process_alive" for event in events)
                    if mode == "cancel":
                        request_cancel(session, session.get(Run, rid))
                        session.commit()
                expected = "canceled" if mode == "cancel" else "interrupted"
                wait_for(lambda: recover(rid) == expected, seconds=35)
                state = inspect_job(rid)
                assert not state["alive"] and state["cleanup_confirmed"] is True
                assert state["pid"] == launched["pid"]
                assert state.get("stdout", "").count("RECOVERY_PROBE_STARTED") == 1
                assert not subprocess.check_output(
                    ["docker", "ps", "-aq", "--filter", f"label=ai-station.python.owner={rid}"], text=True
                ).strip(), "An owned CPU container remains"
                with session_factory()() as session:
                    row = session.get(Run, rid)
                    events = list(session.scalars(select(RunEvent).where(RunEvent.run_id == rid)))
                    assert not list(session.scalars(select(Artifact).where(Artifact.run_id == rid)))
                    assert row.status == expected
                    assert not any(event.event_type == "run.requeued" for event in events)
                    assert sum(event.event_type == "executor.started" for event in events) == 1
                    results.append(
                        {
                            "mode": mode,
                            "run_id": rid,
                            "status": row.status,
                            "actual_worker_sigkill": args.failure_target == "worker",
                            "actual_native_runner_sigkill": args.failure_target == "runner",
                            "original_worker_observed_transport_loss": args.failure_target == "runner",
                            "live_owned_process_inspected": True,
                            "owned_container_removed": True,
                            "no_replay_or_output_adoption": True,
                            "events": [event.event_type for event in events],
                        }
                    )
                assert source.read_bytes() == code
            assert (repo / "README.md").read_bytes() == original and (
                repo / ".git/index"
            ).read_bytes() == index
        completed = True
    finally:
        cleanup_confirmed = True
        for rid in jobs:
            try:
                state = inspect_job(rid)
                if state.get("alive") or state.get("completion_pending"):
                    runner.cancel_process(rid)

                def cleaned():
                    final = inspect_job(rid)
                    return (
                        not final.get("alive")
                        and not final.get("completion_pending")
                        and final.get("cleanup_confirmed") is True
                    )

                wait_for(cleaned, seconds=15)
                assert not subprocess.check_output(
                    ["docker", "ps", "-aq", "--filter", f"label=ai-station.python.owner={rid}"], text=True
                ).strip()
            except Exception:
                cleanup_confirmed = False
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        reset_engine()
        os.chdir(original_cwd)
        log.close()
        result = {
            "passed": completed and cleanup_confirmed,
            "actual_cpu_container": bool(started),
            "image_id": image_id,
            "failure_target": args.failure_target,
            "inference_or_gpu_work": False,
            "production_data_or_services_modified": False,
            "cases": results,
            "cleanup_confirmed": cleanup_confirmed,
            "temporary_root": str(root),
            "retained_for_inspection": not cleanup_confirmed,
        }
        (evidence / "result.json").write_text(json.dumps(result, indent=2))
        if cleanup_confirmed:
            import shutil

            shutil.rmtree(root)
    assert completed and cleanup_confirmed, "Recovery or exact owned cleanup was not confirmed"
    print(
        f"PASS actual CPU {args.failure_target} crash: live inspection, no replay/adoption, completion interruption and owned cancellation"
    )


if __name__ == "__main__":
    main()
