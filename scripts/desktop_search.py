"""Prepare one pinned desktop prerequisite before bounded application startup."""

import json
import subprocess
import time

IMAGE = "searxng/searxng@sha256:eb2a404db174d33a04cd9f2e519bcae2ca722a58923510652cc1314be94e8e63"
ARCHITECTURES = {"x86_64": "amd64", "arm64": "arm64"}
FORMAT = '{"os": {{json .Os}}, "arch": {{json .Architecture}}}'


def prepare(engine, package, log, *, stage, canceled=lambda: False):
    if engine.identity is None or package.get("architecture") not in ARCHITECTURES:
        raise ValueError("Search preparation requires the verified native Mac package and engine")
    architecture = ARCHITECTURES[package["architecture"]]

    def present():
        result = subprocess.run(
            engine.command("image", "inspect", IMAGE, "--format", FORMAT),
            env=engine.environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
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
    if present():
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
        if not present():
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
