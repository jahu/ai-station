"""Explicit native desktop consent; never imported by the application or Runner."""

import grp
import os
import pwd
import stat
import subprocess
from pathlib import Path

SOCKET = Path("/run/docker.sock")
HELPER = Path("/usr/libexec/ai-station/docker-access")
STATION = Path("/usr/lib/ai-station/station")
POLICY = Path("/usr/share/polkit-1/actions/org.ai-station.docker-access.policy")


class DockerAccessNeeded(RuntimeError):
    def __init__(self):
        super().__init__(
            "Docker is installed, but your account cannot use it. Open the installed AI Station "
            "desktop application to review local Docker access, or ask your system administrator."
        )


def needed(endpoint):
    if endpoint not in {"unix:///run/docker.sock", "unix:///var/run/docker.sock"}:
        return False
    try:
        info = SOCKET.lstat()
        group = grp.getgrnam("docker")
        return bool(
            os.getuid() >= 1000
            and stat.S_ISSOCK(info.st_mode)
            and info.st_uid == 0
            and info.st_gid == group.gr_gid != 0
            and stat.S_IMODE(info.st_mode) == 0o660
            and group.gr_gid not in {*os.getgroups(), os.getgid()}
        )
    except (KeyError, OSError):
        return False


def trusted(path):
    """Only root-owned OS package files and ancestors, never a user bundle."""
    try:
        for part in (path, *path.parents):
            info = part.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
                return False
        info = path.lstat()
        return stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    except OSError:
        return False


def continue_setup(dialog, *, background=False):
    if not all(trusted(path) for path in (HELPER, STATION, POLICY)):
        raise RuntimeError("Install the reviewed OS package before enabling local Docker access")
    if not needed("unix:///run/docker.sock"):
        raise RuntimeError("Docker access changed. Open AI Station again to check your configuration")
    account = pwd.getpwuid(os.getuid())
    group = grp.getgrnam("docker")
    member = account.pw_gid == group.gr_gid or account.pw_name in group.gr_mem
    if (
        dialog(
            "--question",
            "--text="
            + (
                "Your account already has Docker access, but this session has not picked it up. "
                "Continue to reopen AI Station with the updated permissions?"
                if member
                else "One setup step remains: allow your account to use local Docker.\n\n"
                "This adds your account to the Docker group, which grants administrator-level control "
                "of this computer. Your operating system will ask for administrator authentication. "
                "AI Station does not receive your password.\n\n"
                "AI Station itself continues to run as your normal user."
            ),
            "--ok-label=Continue" if member else "--ok-label=Authorize Docker access",
            "--cancel-label=Cancel",
        )
        != 0
    ):
        return False
    if not member:
        result = subprocess.run(
            ["/usr/bin/pkexec", "--disable-internal-agent", str(HELPER)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if result.returncode == 126:
            return False  # The OS authentication dialog was canceled.
        if result.returncode:
            raise RuntimeError(
                "Docker access setup did not finish. No AI Station services were started. "
                "Try again from your desktop session or ask your system administrator."
            )
        if account.pw_name not in grp.getgrnam("docker").gr_mem:
            raise RuntimeError("Docker access could not be confirmed. Sign out and reopen AI Station")
    # sg runs as the same ordinary UID. Only the fixed installed launcher and a
    # parsed boolean are allowed; no caller command, path or shell text is used.
    command = "exec /usr/lib/ai-station/station" + (" --background" if background else "")
    os.execv("/usr/bin/sg", ["sg", "docker", "-c", command])
    raise RuntimeError("Could not reopen AI Station with the updated account permissions")
