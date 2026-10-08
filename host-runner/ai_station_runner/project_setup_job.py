"""Initialize only a new application-owned repository and offline environment."""

import json
import os
import signal
import subprocess
import sys

from ai_station_runner.gitinspect import BASE_CONFIG, git_environment
from ai_station_runner.project_setup import ProjectSetup, directory
from ai_station_runner.worktrees import owned_path


def execute(run_id):
    if os.getpid() != os.getpgrp():
        raise ValueError("Project setup requires an owned process group")
    signal.alarm(120)
    root = directory(run_id)
    body = ProjectSetup.model_validate_json((root / "request.json").read_text())
    if str(body.run_id) != run_id:
        raise ValueError("Project request owner changed")
    relative = f"projects/{body.project_id}"
    repo = owned_path(relative)
    repo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    repo.mkdir(mode=0o700)  # Never adopt/overwrite an existing directory.
    env = git_environment()

    def git(*args):
        subprocess.run(
            [
                "git",
                *BASE_CONFIG,
                "-c",
                "init.templateDir=",
                "-c",
                "commit.gpgSign=false",
                "-c",
                "user.name=AI Station",
                "-c",
                "user.email=ai-station@localhost",
                "-C",
                str(repo),
                *args,
            ],
            env=env,
            check=True,
            timeout=20,
        )

    print("Creating local repository", flush=True)
    git("init", "--initial-branch=main")
    (repo / "README.md").write_text("# " + body.name + "\n\nCreated with AI Station.\n")
    (repo / ".gitignore").write_text(".venv/\n__pycache__/\n*.pyc\n.env\nnode_modules/\ndist/\n")
    git("add", "--", "README.md", ".gitignore")
    git("commit", "-m", "Initialize project")
    git("checkout", "-b", "develop")
    print("Creating Python environment (no downloads)", flush=True)
    subprocess.run([sys.executable, "-m", "venv", str(repo / ".venv")], env=env, check=True, timeout=90)
    report = {
        "run_id": run_id,
        "project_id": str(body.project_id),
        "repo_path": str(repo),
        "relative_path": relative,
        "environment": relative + "/.venv",
        "branches": ["main", "develop"],
    }
    with (root / "report.json").open("x") as handle:
        os.chmod(root / "report.json", 0o600)
        json.dump(report, handle)
    print("Project ready", flush=True)
    signal.alarm(0)


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
