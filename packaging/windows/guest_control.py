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
ACTIONS = frozenset(
    {
        "start",
        "status",
        "open",
        "stop",
        "describe",
        "update-bind",
        "update-poll",
        "update-export",
        "update-result",
        "update-status",
        "update-authorize",
    }
)


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
    port = None
    if args and args[0] == "start":
        if len(args) != 2 or not isinstance(args[1], str) or not args[1].isascii() or not args[1].isdigit():
            raise ValueError("Windows startup requires its selected loopback port")
        port = int(args[1])
        if not 8765 <= port < 8865:
            raise ValueError("Choose a desktop loopback port between 8765 and 8864")
    elif len(args) != 1 or args[0] not in ACTIONS:
        raise ValueError("Choose only start, status, open, stop or describe")
    identity()
    os.umask(0o077)
    os.environ.clear()
    os.environ.update(environment())
    if args[0].startswith("update-") and sys.flags.no_site:
        # New finite operations need the packaged dotenv/native modules. Enable
        # only the root-owned packaged site, as the ordinary station account;
        # -I still excludes user site, ambient Python paths and the working dir.
        python = APP / "python/bin/python3"
        os.execve(str(python), [str(python), "-IB", str(Path(__file__).resolve()), *args], environment())
        return
    sys.path.insert(0, str(APP / "scripts"))
    import desktop

    action = args[0]
    if action.startswith("update-"):
        import desktop_windows_updates as updates

        current = desktop.manifest(APP)
        updates.compatible(current)
        raw = sys.stdin.buffer.readline(8193)
        if len(raw) > 8192 or not raw.endswith(b"\n"):
            raise ValueError("The native update control frame exceeds its bound")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate native update control field")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        root = desktop.state_root()
        if action == "update-export":
            updates.export_package(root, current, value, output=sys.stdout.buffer)
            return
        if action == "update-bind":
            result = updates.bind(root, current, value)
        elif action == "update-poll":
            result = updates.poll(root, current, value)
        elif action == "update-result":
            result = updates.host_result(root, current, value)
        elif action == "update-authorize":
            result = updates.authorize_guest_update(root, value)
        else:
            if not isinstance(value, dict) or set(value) != {"channel_id", "run_id"}:
                raise ValueError("Update status accepts only its native operation identity")
            updates.bound(root, value["channel_id"])
            saved = updates.owner.request(root, updates.uuid(value["run_id"]))
            if saved["request"]["platform"] != "windows-x64":
                raise ValueError("This operation belongs to another native platform")
            result = updates.WindowsUpdates(root, APP, current).inspect(value["run_id"])
        print(json.dumps(result, separators=(",", ":")), flush=True)
        return
    if action == "describe":
        print(
            json.dumps(
                {
                    "desktop_protocol": getattr(desktop, "DESKTOP_PROTOCOL", 0),
                    "windows_update_protocol": 1,
                    "version": desktop.manifest(APP).get("version"),
                }
            ),
            flush=True,
        )
        return
    if action == "start" and getattr(desktop, "DESKTOP_PROTOCOL", 0) != 2:
        raise RuntimeError("The guest desktop does not support this Windows launcher")
    if action in {"start", "open"} and open_existing(desktop):
        return
    if action == "open":
        raise RuntimeError("AI Station is stopped; start it before opening")
    options = ["--console", "--background"] if action == "start" else ["--" + action]
    if port is not None:
        options += ["--host-port", str(port)]
    launcher = APP / "station"
    os.execve(str(launcher), [str(launcher), *options], environment())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
