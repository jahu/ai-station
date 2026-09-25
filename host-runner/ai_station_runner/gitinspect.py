"""Bounded, read-only Git inspection with repository command hooks disabled."""

import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path

from ai_station_runner.config import get_settings
from ai_station_runner.gitops import GitError
from ai_station_runner.security import PathBoundaryError, ensure_within

MAX_OUTPUT = 2 * 1024 * 1024
TIMEOUT = 15.0
BASE_CONFIG = [
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "core.pager=cat",
    "-c",
    "gc.auto=0",
]


def git_environment() -> dict:
    # Shell launch environments can carry GIT_DIR, GIT_WORK_TREE, injected config,
    # or external helpers. Inspection always targets the validated repository.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        GIT_ATTR_NOSYSTEM="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_NO_REPLACE_OBJECTS="1",
    )
    return env


def _read(path: Path, args: list[str], config: list[str] | None = None, *, check=True, shared_group=False):
    command = ["git", *BASE_CONFIG, *(config or []), "-C", str(path), *args]
    try:
        process = subprocess.Popen(
            command,
            env=git_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=not shared_group,
        )
    except OSError as exc:
        raise GitError("Git could not be started") from exc
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + TIMEOUT
    completed = False
    try:
        with selectors.DefaultSelector() as selector:
            for stream in output:
                selector.register(getattr(process, stream), selectors.EVENT_READ, stream)
            size = 0
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GitError("Git inspection exceeded its time limit")
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if size > MAX_OUTPUT:
                        raise GitError("Git inspection output exceeds the 2 MiB limit")
                    output[key.data].extend(chunk)
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            completed = True
    except subprocess.TimeoutExpired as exc:
        raise GitError("Git inspection exceeded its time limit") from exc
    finally:
        # A managed job's inspections stay inside its already-owned group.
        if not completed:
            try:
                if shared_group:
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        process.stdout.close()
        process.stderr.close()
    result = subprocess.CompletedProcess(
        command, code, output["stdout"].decode(errors="replace"), output["stderr"].decode(errors="replace")
    )
    if check and code:
        raise GitError(result.stderr[:4000].strip() or "Git inspection failed")
    return result


class Repository:
    def __init__(self, path: Path, *, shared_group=False):
        if shared_group and os.getpgrp() != os.getpid():
            raise GitError("Shared Git process groups require a managed group leader")
        self.shared_group = shared_group
        self.options = []
        roots = get_settings().roots()
        try:
            self.path = ensure_within(path, roots)
            if not self.path.is_dir():
                raise GitError("Repository path is not a directory")
            if self.read(["rev-parse", "--is-inside-work-tree"]).stdout.strip() != "true":
                raise GitError("Path is not a Git worktree")
            self.path = ensure_within(Path(self.read(["rev-parse", "--show-toplevel"]).stdout.strip()), roots)
            self.git_dir = ensure_within(
                Path(self.read(["rev-parse", "--absolute-git-dir"]).stdout.strip()), roots
            )
            common = self.read(["rev-parse", "--path-format=absolute", "--git-common-dir"]).stdout.strip()
            self.common_dir = ensure_within(Path(common), roots)
            objects = ensure_within(self.common_dir / "objects", roots)
            ensure_within(self.common_dir / "config", roots)
            alternates = ensure_within(objects / "info/alternates", roots)
            if alternates.exists() and alternates.read_text().strip():
                raise GitError("Repositories using alternate object stores are not supported for inspection")
        except PathBoundaryError as exc:
            raise GitError("Repository metadata is outside the configured roots") from exc
        config = self.read(
            [
                "config",
                "--null",
                "--get-regexp",
                r"^(filter\..*\.(clean|smudge|process|required)|extensions\.partialclone|remote\..*\.promisor)$",
            ],
            check=False,
        )
        if config.returncode not in (0, 1):
            raise GitError("Could not inspect repository configuration")
        drivers = set()
        for entry in config.stdout.split("\0"):
            if not entry:
                continue
            key, _, value = entry.partition("\n")
            if key.startswith("filter."):
                driver = key[7:].rsplit(".", 1)[0]
                if not driver or any(char in driver for char in "\n\r\0="):
                    raise GitError("Unsupported Git filter configuration")
                drivers.add(driver)
            elif key == "extensions.partialclone" or value.lower() not in {"false", "no", "off", "0"}:
                raise GitError("Partial clone inspection is disabled to prevent implicit fetches")
        for driver in drivers:
            for setting in ("clean", "smudge", "process"):
                self.options += ["-c", f"filter.{driver}.{setting}="]
            self.options += ["-c", f"filter.{driver}.required=false"]

    def read(self, args, *, check=True):
        return _read(self.path, args, self.options, check=check, shared_group=self.shared_group)

    def branch(self):
        result = self.read(["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        return "HEAD"

    def info(self):
        return {
            "repo_path": str(self.path),
            "git_dir": str(self.git_dir),
            "common_dir": str(self.common_dir),
            "branch": self.branch(),
            "is_git": True,
        }


def validate_repo(path: Path) -> dict:
    return Repository(path).info()


def status(path: Path) -> dict:
    repo = Repository(path)
    porcelain = repo.read(
        ["status", "--porcelain=v1", "--untracked-files=normal", "--ignore-submodules=all"]
    ).stdout
    return {"branch": repo.branch(), "porcelain": porcelain, "dirty": bool(porcelain.strip())}


def diff(path: Path, base: str | None) -> dict:
    if base is not None and (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", base) or ".." in base):
        raise GitError("Base must be a branch name or commit ID, not Git options or a revision expression")
    repo = Repository(path)
    flags = ["diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=all", "--no-color"]
    head = repo.read(["rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"], check=False)
    if base:
        commit = repo.read(["rev-parse", "--verify", "--end-of-options", base + "^{commit}"]).stdout.strip()
        if head.returncode:
            raise GitError("Cannot compare a branch without a commit")
        flags += [commit + "..." + head.stdout.strip(), "--"]
    elif head.returncode == 0:
        flags += [head.stdout.strip(), "--"]
    else:
        flags += ["--cached", "--"]
    return {"diff": repo.read(flags).stdout, "base": base or "HEAD"}
