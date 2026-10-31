"""One foreground supervisor for AI Station's own runner and Compose project."""

from __future__ import annotations

import argparse
import fcntl
import ipaddress
import json
import os
import runpy
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from ai_station_runner.unix_sockets import unix_address
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# Bind-mounted application data must survive shutdown. Never pass --volumes/-v/--rmi.
COMPOSE_DOWN = ("down", "--timeout", "10")
VOLUME_WIPE_FLAGS = frozenset({"-v", "--volumes", "--rmi"})


def configuration(config_file: Path | None = None) -> dict[str, str]:
    load_dotenv(config_file or ROOT / ".env", override=False)
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
        with (
            unix_address(Path(env["AI_STATION_RUNNER_SOCKET"])) as address,
            httpx.Client(
                transport=httpx.HTTPTransport(uds=address),
                base_url="http://runner",
                timeout=1,
            ) as client,
        ):
            response = client.get("/health")
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    if body.get("data_dir") != env["AI_STATION_DATA_HOST_PATH"]:
        raise RuntimeError("The existing Host Runner uses a different data directory")
    if body.get("status") != "ok":
        return False
    # Read this checkout, not a potentially older editable package in the venv.
    expected = runpy.run_path(str(ROOT / "host-runner/ai_station_runner/source_identity.py"))[
        "SOURCE_FINGERPRINT"
    ]
    if body.get("source_fingerprint") != expected:
        raise RuntimeError(
            "The existing Host Runner source differs from this checkout or has no source identity. "
            "Inspect active Runs, then restart its owning service from this checkout. "
            "No existing Runner or workload was stopped."
        )
    return True


def data_preserving_compose_down(compose: list[str]) -> list[str]:
    command = [*compose, *COMPOSE_DOWN]
    if VOLUME_WIPE_FLAGS.intersection(command):
        raise RuntimeError("Compose shutdown must not pass --volumes, -v, or --rmi")
    return command


def ensure_recovery_finished(runtime: Path) -> None:
    marker = runtime / "recovery-pending.json"
    if marker.exists() or marker.is_symlink():
        raise RuntimeError(
            "An offline database recovery is unfinished. Inspect ./scripts/restore.sh --pending, "
            "then finish or abort that recovery before starting AI Station."
        )


def stop_runner(proc: subprocess.Popen | None) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def local_entry_url(client, run, url: str, api_url: str) -> str:
    """Ask only the owned container console for pending first-admin setup."""
    auth = client.get(api_url + "/api/auth")
    if auth.status_code != 200 or not auth.headers.get("content-type", "").startswith("application/json"):
        return url
    body = auth.json()
    if not isinstance(body, dict) or body.get("setup_required") is not True:
        return url
    # A URL fragment is not sent to HTTP servers or in referrers. No HTTP
    # endpoint exposes this proof, and application/agents gain no Docker API.
    return run(
        "exec",
        "-T",
        "ai-station",
        "python",
        "-m",
        "app.bootstrap_setup",
        "--url",
        url,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--no-build", action="store_true", help="Reuse the existing application image")
    parser.add_argument("--config", type=Path, help="Explicit local desktop installation configuration")
    parser.add_argument("--desktop", action="store_true", help="Report readiness to the local desktop parent")
    args = parser.parse_args()
    os.chdir(ROOT)
    env = configuration(args.config) if args.config else configuration()
    if env.get("AI_STATION_LAN_HOST"):
        try:
            address = ipaddress.IPv4Address(env["AI_STATION_LAN_HOST"])
            networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
            if not any(address in ipaddress.ip_network(network) for network in networks):
                raise ValueError("not private")
        except ValueError:
            raise RuntimeError("AI_STATION_LAN_HOST must be a specific private IPv4 address") from None
    if args.dev and env.get("AI_STATION_LAN_HOST"):
        raise RuntimeError("LAN access uses the production UI; Vite development stays on loopback")
    runtime = Path(env["AI_STATION_DATA_HOST_PATH"]) / "runtime"
    runtime.mkdir(exist_ok=True)
    compose = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    if env.get("AI_STATION_LAN_HOST"):
        compose += ["-f", str(ROOT / "compose.lan.yaml")]
    if args.dev:
        compose += ["-f", str(ROOT / "compose.dev.yaml")]

    def run(*arguments, **kwargs):
        return subprocess.run([*compose, *arguments], env=env, check=True, **kwargs)

    with (runtime / "launcher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("AI Station is already supervised for this data directory")
        ensure_recovery_finished(runtime)
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
            runner_health(env)
            if not args.no_build:
                # One shared image; Docker build works even when the optional
                # buildx plugin is absent from a workstation's Compose install.
                subprocess.run(
                    ["docker", "build", "-t", env.get("AI_STATION_APP_IMAGE", "ai-station:local"), str(ROOT)],
                    env=env,
                    check=True,
                )
            # Building can take minutes; the preflight Runner may have exited
            # or been replaced. Recheck before reusing it.
            if not runner_health(env):
                proc = subprocess.Popen(
                    [sys.executable, *(["-I"] if args.desktop else []), "-m", "ai_station_runner.main"],
                    env=env,
                )
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
                api_url = f"http://127.0.0.1:{env.get('AI_STATION_PORT', '8765')}"
                url = local_entry_url(client, run, url, api_url)
            if args.desktop:
                # Private pipe to the owning desktop process. The parent consumes
                # this setup authority without persisting it in ordinary logs.
                print("AI_STATION_READY " + json.dumps({"url": url}), flush=True)
            else:
                print(f"\nAI Station is ready: {url}\nPress Ctrl+C to stop this deployment.\n", flush=True)
            if env.get("AI_STATION_LAN_HOST"):
                print(f"Private LAN: http://{env['AI_STATION_LAN_HOST']}:{port}", flush=True)
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
                    subprocess.run(data_preserving_compose_down(compose), env=env, check=True)
            finally:
                stop_runner(proc)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, httpx.HTTPError) as error:
        raise SystemExit(str(error))
