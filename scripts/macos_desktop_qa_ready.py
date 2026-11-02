"""Wait for an actual fresh QA Desktop engine, rather than just its GUI process."""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from macos_transport_probe import ARCHITECTURES, INFO, command, connection  # noqa: E402


def wait_for_engine(timeout=180):
    if platform.system() != "Darwin" or platform.machine() != "x86_64" or os.geteuid() == 0:
        raise ValueError("This developer experiment requires an ordinary user on the Intel Mac host")
    deadline = time.monotonic() + timeout
    selected = None
    env = {"PATH": os.defpath, "HOME": str(Path.home()), "LANG": "C"}
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            if selected is None:
                selected = connection(
                    lambda argv, **kwargs: command(argv, **kwargs, check=False, timeout=min(5, remaining))
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            binary, endpoint = selected
            code, data = command(
                [binary, "--host", endpoint, "info", "--format", INFO],
                env=env,
                check=False,
                timeout=min(5, remaining),
            )
            if code == 0:
                value = json.loads(data)
                if (
                    not isinstance(value, dict)
                    or value.get("os") != "linux"
                    or value.get("system") != "Docker Desktop"
                    or ARCHITECTURES.get(value.get("arch")) != "amd64"
                ):
                    raise ValueError("The ready engine is not the expected local Intel Docker Desktop")
                return {"engine_ready": True, "engine": value, "consumer_installer_qualified": False}
        except (RuntimeError, subprocess.TimeoutExpired):
            # Initial context creation/daemon boot may follow GUI launch. Never
            # restart the app or issue a model/container workload while waiting.
            pass
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise RuntimeError("Docker Desktop GUI opened, but its local Linux engine did not become ready")


if __name__ == "__main__":
    print(json.dumps(wait_for_engine(), sort_keys=True))
