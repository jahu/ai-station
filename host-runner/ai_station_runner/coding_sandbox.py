"""Fixed native isolation policy for validation inside an owned coding worktree.

This internal adapter does not expose an execution endpoint or enable coding CLIs.
"""

import json
import os
import shutil
from pathlib import Path


class SandboxUnavailable(RuntimeError):
    pass


def cursor_sandbox_binary() -> Path:
    cli = shutil.which("cursor-agent") or shutil.which("agent")
    if not cli:
        raise SandboxUnavailable("Cursor's native sandbox helper is unavailable")
    helper = Path(cli).resolve().parent / "cursorsandbox"
    if not helper.is_file() or not os.access(helper, os.X_OK):
        raise SandboxUnavailable("The installed Cursor CLI has no executable native sandbox helper")
    return helper


def validation_policy(workspace: Path, git_common_dir: Path) -> dict:
    workspace = workspace.resolve(strict=True)
    git_common_dir = git_common_dir.resolve(strict=True)
    if not workspace.is_dir() or not git_common_dir.is_dir():
        raise SandboxUnavailable("Worktree and Git metadata must be directories")
    # No shell environment, home directory, credential directory or application
    # data root is granted access. The caller must first verify worktree ownership.
    system_paths = ["/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache", "/etc/alternatives"]
    return {
        "sandbox": {
            "type": "workspace_readwrite",
            "cwd": str(workspace),
            "readBoundary": "workspace",
            "hardcodedReadPaths": [path for path in system_paths if Path(path).exists()]
            + [str(git_common_dir)],
            "additionalReadonlyPaths": {
                str(workspace): [
                    ".git",
                    ".git/**",
                    ".cursor",
                    ".cursor/**",
                    ".codex",
                    ".codex/**",
                    ".agents",
                    ".agents/**",
                ],
            },
            "additionalReadwritePaths": [],
            "disableTmpWrite": True,
            "networkAccess": False,
        },
        "networkPolicyStrict": True,
    }


NETWORK_READ_PATHS = (
    "/etc/ssl",
    "/etc/pki",
    "/etc/ssl/certs",
    "/etc/ca-certificates",
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/nsswitch.conf",
    "/usr/share/ca-certificates",
    "/usr/lib/ssl",
)


def dependency_policy(workspace: Path, git_common_dir: Path, *, network: bool) -> dict:
    policy = validation_policy(workspace, git_common_dir)
    sandbox = policy["sandbox"]
    sandbox["networkAccess"] = bool(network)
    # pip reads distro/MIME metadata even for offline vendor installation.
    # Grant only public OS release files, never all /etc or host process data.
    release_paths = [
        path for path in ("/etc/os-release", "/etc/debian_version", "/etc/mime.types") if Path(path).is_file()
    ]
    sandbox["hardcodedReadPaths"] = list(dict.fromkeys([*sandbox["hardcodedReadPaths"], *release_paths]))
    if network:
        extra = [path for path in NETWORK_READ_PATHS if Path(path).exists()]
        sandbox["hardcodedReadPaths"] = list(dict.fromkeys([*sandbox["hardcodedReadPaths"], *extra]))
    return policy


def write_policy(path: Path, workspace: Path, git_common_dir: Path, policy: dict | None = None) -> Path:
    workspace = workspace.resolve(strict=True)
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise SandboxUnavailable("Policy path must be canonical without symlink redirection")
    if path.is_relative_to(workspace):
        raise SandboxUnavailable("Sandbox policy must stay outside the writable worktree")
    policy = policy or validation_policy(workspace, git_common_dir)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(policy, handle)
    return path


def validation_argv(policy: Path, command: list[str], *, preflight: bool = False) -> list[str]:
    if not command or not command[0] or any(not isinstance(arg, str) or "\0" in arg for arg in command):
        raise ValueError("A structured project command is required")
    return [
        str(cursor_sandbox_binary()),
        "--policy",
        str(policy),
        *(["--preflight-only"] if preflight else []),
        "--",
        *command,
    ]
