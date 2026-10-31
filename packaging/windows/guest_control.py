#!/usr/lib/ai-station/python/bin/python3 -IBS
"""Fixed ordinary-user desktop operations inside the dedicated WSL2 distribution."""

import fcntl
import json
import os
import pwd
import stat
import sys
from pathlib import Path

APP = Path("/usr/lib/ai-station")
USER = "station"
HOME = Path("/home/station")
ACTIONS = frozenset({"start", "status", "open", "stop"})


def trusted(path):
    for item in (path, *path.parents):
        info = item.lstat()
        if item.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("The installed guest application must remain root-owned and immutable")


def identity():
    if os.getuid() != os.geteuid() or os.getuid() < 1000:
        raise ValueError("Launch AI Station as its ordinary guest account, never root")
    account = pwd.getpwuid(os.getuid())
    if account.pw_name != USER or Path(account.pw_dir) != HOME:
        raise ValueError("This operation belongs only to the dedicated station guest account")
    if HOME.is_symlink() or HOME.stat().st_uid != os.getuid() or HOME.stat().st_mode & 0o077:
        raise ValueError("The guest home must remain private to its account")
    trusted(APP / "station")


def environment():
    # Windows shell/other WSL environments cannot supply paths, Python, Docker
    # context, browser commands or another station's configuration.
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": str(HOME),
        "USER": USER,
        "LOGNAME": USER,
        "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": "/run/user/" + str(os.getuid()),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/" + str(os.getuid()) + "/bus",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
    }


def open_existing(desktop):
    root = desktop.state_root()
    path = root / "desktop.lock"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("The desktop owner lock must be an owned regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Read authority only while observing the actual live owner's lock.
            value = desktop.ready_info(root)
            if value is None:
                raise RuntimeError("AI Station is still starting; wait for its existing owner")
            if not value.get("instance_id"):
                raise RuntimeError("Restart this desktop version to obtain its browser identity")
            print(desktop.READY + json.dumps(value), flush=True)
            return True
        return False
    finally:
        os.close(descriptor)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in ACTIONS:
        raise ValueError("Choose only start, status, open or stop")
    identity()
    os.umask(0o077)
    os.environ.clear()
    os.environ.update(environment())
    sys.path.insert(0, str(APP / "scripts"))
    import desktop

    action = args[0]
    if action in {"start", "open"} and open_existing(desktop):
        return
    if action == "open":
        raise RuntimeError("AI Station is stopped; start it before opening")
    options = ["--console", "--background"] if action == "start" else ["--" + action]
    launcher = APP / "station"
    os.execve(str(launcher), [str(launcher), *options], environment())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
