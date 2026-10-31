"""Single runner per data root, bound only to a private Unix socket."""

import fcntl
import os
import signal
import socket
from pathlib import Path

import uvicorn

from ai_station_runner.app import app, manager
from ai_station_runner.config import get_settings
from ai_station_runner.unix_sockets import unix_address


def main() -> None:
    os.umask(0o077)
    settings = get_settings()
    runtime = settings.host_data_dir() / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A Host Runner already owns this data directory")
        path = Path(settings.socket_path())
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(path.parent, 0o700)
        if path.exists():
            with socket.socket(socket.AF_UNIX) as probe:
                try:
                    with unix_address(path) as address:
                        probe.connect(address)
                except ConnectionRefusedError:
                    path.unlink()
                else:
                    raise SystemExit("The configured socket already has a listener")
        with socket.socket(socket.AF_UNIX) as listener:
            with unix_address(path) as address:
                listener.bind(address)
            os.chmod(path, 0o600)
            listener.listen(128)
            try:
                # Uvicorn replays termination signals after graceful shutdown.
                # Convert that replay to normal unwinding so the socket and
                # ownership lock are always cleaned up.
                def terminate(_signum, _frame):
                    raise SystemExit(0)

                signal.signal(signal.SIGTERM, terminate)
                signal.signal(signal.SIGINT, terminate)
                from ai_station_runner.tailnet_api import manager as private_manager

                try:
                    private_manager().restore()
                except (ValueError, OSError, KeyError, TypeError):
                    # No private paths, auth links or node keys in ordinary logs.
                    print("Private access recovery needs operator inspection", flush=True)
                uvicorn.Server(uvicorn.Config(app, log_level="info")).run(sockets=[listener])
            finally:
                try:
                    manager().shutdown()
                finally:
                    path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
