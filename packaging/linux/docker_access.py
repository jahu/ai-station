#!/usr/lib/ai-station/python/bin/python3 -IBS
"""One package-owned OS setup action. No application imports or caller arguments."""

import grp
import os
import pwd
import re
import stat
import subprocess
import sys
from pathlib import Path

SOCKET = Path("/run/docker.sock")


def grant():
    if len(sys.argv) != 1 or os.getuid() != 0 or os.geteuid() != 0:
        raise ValueError("Use the operating system authentication dialog for this setup action")
    invoking = os.environ.get("PKEXEC_UID", "")
    if not re.fullmatch(r"[1-9][0-9]{3,9}", invoking) or not 1000 <= int(invoking) < 2**32:
        raise ValueError("A normal local invoking account is required")
    uid = int(invoking)
    account = pwd.getpwuid(uid)
    group = grp.getgrnam("docker")
    info = SOCKET.lstat()
    if (
        account.pw_uid != uid
        or group.gr_gid == 0
        or not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != group.gr_gid
        or stat.S_IMODE(info.st_mode) != 0o660
    ):
        raise ValueError("The local Docker socket or account changed; setup was not applied")
    if account.pw_gid == group.gr_gid or account.pw_name in group.gr_mem:
        return
    if pwd.getpwnam(account.pw_name).pw_uid != uid:
        raise ValueError("The invoking account changed; setup was not applied")
    subprocess.run(
        ["/usr/sbin/usermod", "--append", "--groups", "docker", "--", account.pw_name],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        cwd="/",
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    if account.pw_name not in grp.getgrnam("docker").gr_mem:
        raise RuntimeError("Account access could not be confirmed; inspect OS account settings")


if __name__ == "__main__":
    try:
        grant()
    except (KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
