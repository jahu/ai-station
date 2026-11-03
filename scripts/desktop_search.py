"""Prepare one pinned desktop prerequisite before bounded application startup."""

import json
import platform
import subprocess
import time

IMAGE = "searxng/searxng@sha256:eb2a404db174d33a04cd9f2e519bcae2ca722a58923510652cc1314be94e8e63"
ARCHITECTURES = {"x86_64": "amd64", "arm64": "arm64"}
FORMAT = '{"os": {{json .Os}}, "arch": {{json .Architecture}}}'
WAITING = "Waiting for Docker Desktop's local engine…"


def prepare(engine, package, log, *, stage, canceled=lambda: False):
    if engine.identity is not None:
        if package.get("architecture") not in ARCHITECTURES:
            raise ValueError("Search preparation requires a supported verified native Mac package")
        architecture = ARCHITECTURES[package["architecture"]]
    elif platform.system() == "Linux" and platform.machine().lower() in {"x86_64", "amd64"}:
        # Linux packages and the owned Windows WSL guest share this fixed
        # platform. They have no Mac architecture field or Desktop handoff.
        architecture = "amd64"
    else:
        raise ValueError("Search preparation requires a supported desktop package and engine")

    def present():
        # Desktop can return cached metadata while its Linux engine is asleep
        # or still starting. Retry only timed-out read-only inspection, never
        # an execution or a failed identity check, in its own bounded phase.
        deadline = time.monotonic() + 180 if engine.identity is not None else None
        attempt_timeout = 15
        waiting = False
        while True:
            if canceled():
                return None
            if waiting:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Docker Desktop's local engine did not become responsive")
                attempt_timeout = min(5, remaining)
            try:
                result = subprocess.run(
                    engine.command("image", "inspect", IMAGE, "--format", FORMAT),
                    env=engine.environment,
                    capture_output=True,
                    text=True,
                    timeout=attempt_timeout,
                )
                break
            except subprocess.TimeoutExpired:
                if deadline is None:
                    raise
                if not waiting:
                    stage(WAITING)
                    waiting = True
                time.sleep(0.2)
        if result.returncode:
            return False
        if len(result.stdout) > 4096:
            raise ValueError("Unexpected search image metadata")
        if json.loads(result.stdout) != {"os": "linux", "arch": architecture}:
            raise ValueError("The cached search image does not match this package's platform")
        return True

    if canceled():
        return False
    stage("Checking the local web-search component…")
    cached = present()
    if cached is None:
        return False
    if cached:
        return not canceled()
    if canceled():
        return False
    stage("Downloading the web-search component. This only happens once…")
    process = subprocess.Popen(
        engine.command("image", "pull", "--platform", "linux/" + architecture, IMAGE),
        env=engine.environment,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 600
        while process.poll() is None:
            if canceled():
                return False
            if time.monotonic() >= deadline:
                raise TimeoutError("The web-search component could not finish downloading; try again")
            time.sleep(0.2)
        if process.returncode:
            raise RuntimeError("The web-search component could not be downloaded; check your connection")
        verified = present()
        if verified is None:
            return False
        if not verified:
            raise RuntimeError("The downloaded web-search component could not be verified")
        return not canceled()
    finally:
        if process.poll() is None:
            process.terminate()  # Exact immediate, unreaped download client only.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
