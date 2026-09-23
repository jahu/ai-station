"""One foreground supervisor for AI Station's own runner and Compose project."""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def configuration() -> dict[str, str]:
    load_dotenv(ROOT / ".env", override=False)
    env = dict(os.environ)
    data = Path(env.get("AI_STATION_DATA_HOST_PATH") or ROOT / "data").expanduser().resolve()
    sock = (
        Path(env.get("AI_STATION_RUNNER_SOCKET") or data / "runtime/runner/runner.sock")
        .expanduser()
        .resolve()
    )
    if sock.name != "runner.sock":
        raise RuntimeError("AI_STATION_RUNNER_SOCKET must use the filename runner.sock for Compose mapping")
    env.update(
        AI_STATION_DATA_HOST_PATH=str(data),
        AI_STATION_DATA_DIR=str(data),
        AI_STATION_RUNNER_SOCKET=str(sock),
        AI_STATION_RUNNER_SOCKET_DIR=str(sock.parent),
        AI_STATION_UID=str(os.getuid()),
        AI_STATION_GID=str(os.getgid()),
    )
    data.mkdir(parents=True, exist_ok=True)
    sock.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    return env


def runner_health(env: dict) -> bool:
    try:
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=env["AI_STATION_RUNNER_SOCKET"]),
            base_url="http://runner",
            timeout=1,
        ) as client:
            response = client.get("/health")
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    if body.get("data_dir") != env["AI_STATION_DATA_HOST_PATH"]:
        raise RuntimeError("The existing Host Runner uses a different data directory")
    return body.get("status") == "ok"


def stop_runner(proc: subprocess.Popen | None) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--no-build", action="store_true", help="Reuse the existing application image")
    args = parser.parse_args()
    os.chdir(ROOT)
    env = configuration()
    runtime = Path(env["AI_STATION_DATA_HOST_PATH"]) / "runtime"
    runtime.mkdir(exist_ok=True)
    compose = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    if args.dev:
        compose += ["-f", str(ROOT / "compose.dev.yaml")]

    def run(*arguments, **kwargs):
        return subprocess.run([*compose, *arguments], env=env, check=True, **kwargs)

    with (runtime / "launcher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("AI Station is already supervised for this data directory")
        # Never attach cleanup ownership to a pre-existing Compose deployment.
        if run("ps", "--all", "--quiet", capture_output=True, text=True).stdout.strip():
            raise RuntimeError(
                "This Compose project already has containers; inspect them before starting another supervisor"
            )
        proc = None
        started = False

        def shutdown(_signum, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        try:
            if not args.no_build:
                # One shared image; Docker build works even when the optional
                # buildx plugin is absent from a workstation's Compose install.
                subprocess.run(["docker", "build", "-t", "ai-station:local", str(ROOT)], env=env, check=True)
            if not runner_health(env):
                proc = subprocess.Popen([sys.executable, "-m", "ai_station_runner.main"], env=env)
                deadline = time.monotonic() + 20
                while not runner_health(env):
                    if proc.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Host Runner did not become healthy")
                    time.sleep(0.2)
            started = True
            run("up", "--no-build", "--detach", "--wait", "--wait-timeout", "120")
            port = "5173" if args.dev else env.get("AI_STATION_PORT", "8765")
            url = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=3) as client:
                client.get(url).raise_for_status()
            print(f"\nAI Station is ready: {url}\nPress Ctrl+C to stop this deployment.\n", flush=True)
            while True:
                if proc is not None and proc.poll() is not None:
                    raise RuntimeError("Host Runner exited unexpectedly")
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping AI Station…", flush=True)
        finally:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:
                if started:
                    run("down", "--timeout", "10")
            finally:
                stop_runner(proc)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, httpx.HTTPError) as error:
        raise SystemExit(str(error))
