import os
import stat
import subprocess
import sys
import time

import httpx


def test_runner_socket_is_private_and_second_runner_cannot_replace_it(tmp_path):
    socket_path = tmp_path / "socket" / "runner.sock"
    env = {
        **os.environ,
        "AI_STATION_DATA_HOST_PATH": str(tmp_path / "data"),
        "AI_STATION_RUNNER_SOCKET": str(socket_path),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "ai_station_runner.main"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not socket_path.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.05)
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(socket_path.parent.stat().st_mode) == 0o700
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket_path)), base_url="http://runner"
        ) as client:
            assert client.get("/health").json()["status"] == "ok"
            duplicate = subprocess.run(
                [sys.executable, "-m", "ai_station_runner.main"], env=env, capture_output=True, timeout=10
            )
            assert duplicate.returncode != 0
            assert client.get("/health").status_code == 200
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert not socket_path.exists()
