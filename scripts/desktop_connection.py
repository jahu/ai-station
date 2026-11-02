"""Internal Linux connection service for the private native Mac Runner."""

import argparse
import asyncio
import http.client
import json
import os
import signal
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desktop_link  # noqa: E402

SOCKET = Path("/runner/runner.sock")
CREDENTIALS = Path("/connection")


def port():
    value = os.environ.get("AI_STATION_NATIVE_CONNECTION_PORT", "")
    if not value.isascii() or not value.isdecimal() or not 1024 <= int(value) <= 65535:
        raise ValueError("The native connection requires its supervisor-selected port")
    return int(value)


def health():
    """A fixed HTTP health request traverses both sockets and authenticated TLS."""
    connection = http.client.HTTPConnection("runner", timeout=3)
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        channel.settimeout(3)
        channel.connect(str(SOCKET))
        connection.sock = channel
        connection.request("GET", "/health", headers={"Connection": "close"})
        response = connection.getresponse()
        raw = response.read(65537)
        if response.status != 200 or len(raw) > 65536:
            return False
        value = json.loads(raw)
        return isinstance(value, dict) and value.get("status") == "ok"
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()
        channel.close()


async def serve():
    if sys.platform != "linux" or os.geteuid() == 0:
        raise ValueError("The connection service requires an ordinary Linux container user")
    selected = port()
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, done.set)
    try:
        async with desktop_link.proxy(CREDENTIALS, SOCKET, selected):
            await done.wait()
    finally:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()
    try:
        if args.health:
            raise SystemExit(0 if health() else 1)
        asyncio.run(serve())
    except (OSError, ValueError, RuntimeError):
        # No request, certificate data, native paths or tracebacks in app logs.
        raise SystemExit("The private native Runner connection is unavailable") from None
