"""Publish one approved task commit with isolated Git configuration."""

import fcntl
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import time

from ai_station_runner.publication import directory, inspect_commit, load_request
from ai_station_runner.worktrees import owned_path


def command(argv, *, env, cwd, deadline, allowed=(0,)):
    proc = subprocess.Popen(
        argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    output = {"stdout": bytearray(), "stderr": bytearray()}
    with selectors.DefaultSelector() as selector:
        for stream in output:
            selector.register(getattr(proc, stream), selectors.EVENT_READ, stream)
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise RuntimeError("Publication timed out; inspect GitHub before another request")
            for key, _ in selector.select(0.2):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(data)
                if sum(map(len, output.values())) > 1048576:
                    raise RuntimeError("Publication exceeded its output limit; inspect GitHub")
    code = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
    proc.stdout.close()
    proc.stderr.close()
    if code not in allowed:
        # Provider stderr can contain credential details. Keep it out of events.
        raise RuntimeError(
            f"GitHub publication command failed (exit {code}); check GitHub access and inspect the repository"
        )
    return bytes(output["stdout"]).decode("utf-8", errors="strict"), code


def execute(run_id):
    if os.getpid() != os.getpgrp():
        raise ValueError("Publication requires an owned process group")
    body, commit = load_request(run_id)
    root = directory(run_id)
    lock_path = owned_path(f"runtime/validation-worktrees/{commit['worktree_run_id']}.lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        repo, preview = inspect_commit(commit, shared_group=True)
        if preview["repository"] != body.repository or preview["commit"] != body.commit:
            raise ValueError("Approved publication target changed")
        if preview["branch"] in {*body.protected_branches, "main", "master", body.base}:
            raise ValueError("Protected branch publication is forbidden")
        git, gh = shutil.which("git"), shutil.which("gh")
        if not git or not gh:
            raise ValueError("Git and GitHub CLI must be installed")
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "XDG_CONFIG_HOME", "GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN")
            if key in os.environ
        }
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_TERMINAL_PROMPT="0",
            GIT_ALLOW_PROTOCOL="https",
            GIT_NO_REPLACE_OBJECTS="1",
            GIT_NO_LAZY_FETCH="1",
            GH_HOST="github.com",
            GH_PROMPT_DISABLED="1",
            GH_PAGER="cat",
            GH_EDITOR="/bin/false",
            CI="1",
        )
        deadline = time.monotonic() + 300
        export = root / "export.git"
        fmt = repo.read(["rev-parse", "--show-object-format"]).stdout.strip()
        if fmt not in {"sha1", "sha256"}:
            raise ValueError("Unsupported Git object format")
        command(
            [
                git,
                "init",
                "--bare",
                "--template=",
                "--initial-branch=ai/export",
                f"--object-format={fmt}",
                str(export),
            ],
            env=env,
            cwd=root,
            deadline=deadline,
        )
        env.update(GIT_DIR=str(export), GIT_OBJECT_DIRECTORY=str((repo.common_dir / "objects").resolve()))
        options = [
            git,
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "gc.auto=0",
            "-c",
            "credential.helper=",
            "-c",
            f"credential.helper=!{shlex.quote(gh)} auth git-credential",
            "-c",
            "credential.useHttpPath=true",
        ]
        url = f"https://github.com/{body.repository}.git"
        ref = f"refs/heads/{preview['branch']}"
        command([*options, "check-ref-format", ref], env=env, cwd=root, deadline=deadline)
        command(
            [*options, "check-ref-format", f"refs/heads/{body.base}"], env=env, cwd=root, deadline=deadline
        )
        base, _ = command(
            [*options, "ls-remote", "--exit-code", url, f"refs/heads/{body.base}"],
            env=env,
            cwd=root,
            deadline=deadline,
        )
        if base.strip().split() != [commit["parent"], f"refs/heads/{body.base}"]:
            raise ValueError(
                "Task parent differs from the current remote integration head; refresh the task before publishing"
            )
        existing, _ = command(
            [*options, "ls-remote", "--exit-code", url, ref],
            env=env,
            cwd=root,
            deadline=deadline,
            allowed=(0, 2),
        )
        if existing.strip() and existing.strip().split() != [body.commit, ref]:
            raise ValueError(
                "Remote task branch already has another commit; inspect it instead of overwriting"
            )
        progress = {"run_id": run_id, "source_run_id": str(body.source_run_id), **preview, "base": body.base}

        def record(stage):
            progress["stage"] = stage
            temporary = root / "progress.tmp"
            temporary.write_text(json.dumps(progress))
            temporary.chmod(0o600)
            os.replace(temporary, root / "progress.json")
            print(f"Publication: {stage}", flush=True)

        record("push_started")
        command(
            [*options, "push", "--porcelain", "--no-verify", url, f"{body.commit}:{ref}"],
            env=env,
            cwd=root,
            deadline=deadline,
        )
        record("push_confirmed")
        description = root / "pr-body.md"
        description.write_text(body.body)
        description.chmod(0o600)
        record("pr_requested")
        result, _ = command(
            [
                gh,
                "pr",
                "create",
                "--repo",
                body.repository,
                "--base",
                body.base,
                "--head",
                preview["branch"],
                "--title",
                body.title,
                "--body-file",
                str(description),
                "--draft",
                "--no-maintainer-edit",
            ],
            env=env,
            cwd=root,
            deadline=deadline,
        )
        pr_url = result.strip()
        if not re.fullmatch(
            r"https://github\.com/" + re.escape(body.repository) + r"/pull/[1-9][0-9]*", pr_url
        ):
            raise ValueError("GitHub returned an unexpected PR URL; inspect the repository")
        progress["pr_url"] = pr_url
        record("succeeded")
        with (root / "report.json").open("x") as handle:
            os.chmod(handle.name, 0o600)
            json.dump(progress, handle)


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        # Git/credential-helper descendants share this owned group. No child is
        # left behind on deadline/output limits or a failed network operation.
        if os.getpgrp() == os.getpid():
            os.killpg(os.getpid(), signal.SIGTERM)
        raise SystemExit(1) from error
