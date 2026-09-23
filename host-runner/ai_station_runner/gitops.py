"""Typed git operations. No shell, no force-push, no protected-branch writes."""

from __future__ import annotations

import subprocess
from pathlib import Path

SHELLS = {"sh", "bash", "zsh", "dash", "fish", "sudo", "su"}


class GitError(Exception):
    pass


def _run(argv: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise GitError(completed.stderr.strip() or completed.stdout.strip() or "git failed")
    return completed


def validate_repo(path: Path) -> dict:
    if not path.is_dir():
        raise GitError("Repository path is not a directory")
    inside = _run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"])
    if inside.stdout.strip() != "true":
        raise GitError("Path is not a git work tree")
    branch = _run(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    return {"repo_path": str(path), "branch": branch, "is_git": True}


def status(path: Path) -> dict:
    validate_repo(path)
    porcelain = _run(["git", "-C", str(path), "status", "--porcelain"]).stdout
    branch = _run(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    return {"branch": branch, "porcelain": porcelain, "dirty": bool(porcelain.strip())}


def diff(path: Path, base: str | None) -> dict:
    validate_repo(path)
    if base:
        completed = _run(["git", "-C", str(path), "diff", f"{base}...HEAD"], check=False)
        if completed.returncode != 0:
            completed = _run(["git", "-C", str(path), "diff", base], check=False)
    else:
        completed = _run(["git", "-C", str(path), "diff", "HEAD"], check=False)
    return {"diff": completed.stdout, "base": base or "HEAD"}


def add_worktree(repo: Path, dest: Path, branch: str, base: str) -> dict:
    validate_repo(repo)
    if not branch.startswith("ai/"):
        raise GitError("Worktree branches must start with ai/")
    if dest.exists():
        raise GitError("Worktree destination already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "-C", str(repo), "worktree", "add", "-b", branch, str(dest), base])
    return {"branch": branch, "path": str(dest)}


def remove_worktree(repo: Path, dest: Path, *, owned: bool) -> dict:
    if not owned:
        raise GitError("Refusing to remove a worktree AI Station does not own")
    validate_repo(repo)
    _run(["git", "-C", str(repo), "worktree", "remove", "--force", str(dest)])
    return {"removed": str(dest)}


def commit(path: Path, branch: str, protected: list[str], message: str) -> dict:
    current = status(path)
    if current["branch"] != branch:
        raise GitError("Refusing to commit: checked out branch does not match the task branch")
    if branch in set(protected) or branch in {"main", "master"} or not branch.startswith("ai/"):
        raise GitError("Refusing to commit on a protected branch")
    if not current["dirty"]:
        return {"committed": False, "reason": "clean"}
    _run(["git", "-C", str(path), "add", "-A"])
    _run(["git", "-C", str(path), "commit", "-m", message])
    sha = _run(["git", "-C", str(path), "rev-parse", "HEAD"]).stdout.strip()
    return {"committed": True, "sha": sha, "branch": branch}


def apply_diff(path: Path, diff_text: str) -> dict:
    validate_repo(path)
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---")) and ".." in line:
            raise GitError("Diff path escapes the worktree")
    temporary = path / ".ai-station.patch"
    temporary.write_text(diff_text)
    try:
        _run(["git", "-C", str(path), "apply", "--check", str(temporary)])
        _run(["git", "-C", str(path), "apply", str(temporary)])
    finally:
        temporary.unlink(missing_ok=True)
    return {"applied": True}


def create_pull_request(path: Path, branch: str, base: str, title: str, body: str) -> dict:
    validate_repo(path)
    if branch in {"main", "master"} or not branch.startswith("ai/"):
        raise GitError("Refusing to open a pull request from a protected branch")
    if shutil_which("gh") is None:
        raise GitError("GitHub CLI is unavailable")
    completed = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--head",
            branch,
            "--base",
            base,
            "--title",
            title,
            "--body",
            body,
        ],
        cwd=str(path),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise GitError(completed.stderr.strip() or "gh pr create failed")
    return {"url": completed.stdout.strip(), "branch": branch, "base": base}


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def run_project_command(path: Path, argv: list[str], allowed: list[list[str]]) -> dict:
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
        raise GitError("Command must be an argv list")
    if list(argv) not in [list(item) for item in allowed]:
        raise GitError("Command is not one of the project's configured commands")
    executable = Path(argv[0]).name
    if executable in SHELLS:
        raise GitError("Shell executables are not accepted as project commands")
    completed = subprocess.run(
        argv,
        cwd=str(path),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-4000:],
    }
