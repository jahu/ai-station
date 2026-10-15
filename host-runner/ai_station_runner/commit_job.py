"""Commit only reviewed snapshots using a private index and atomic ref update."""

import fcntl
import hashlib
import json
import os
import subprocess
import sys

from ai_station_runner.coding_files import read_review_files
from ai_station_runner.gitinspect import BASE_CONFIG, Repository, git_environment
from ai_station_runner.reviewed_commits import directory, load_request
from ai_station_runner.worktrees import load_manifest, owned_path, save_manifest


def execute(run_id):
    if os.getpid() != os.getpgrp():
        raise ValueError("Commit job requires an owned process group")
    body, review = load_request(run_id)
    record = load_manifest(review["worktree_run_id"])
    root = directory(run_id)
    workspace = owned_path(record["relative_path"])
    lock_path = owned_path(f"runtime/validation-worktrees/{record['run_id']}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        repo = Repository(workspace, shared_group=True)
        parent = repo.read(["rev-parse", "HEAD"]).stdout.strip()
        if (
            record["state"] != "ready"
            or record["project_id"] != str(body.project_id)
            or record["branch"] != review["branch"]
            or parent != record.get("head_commit", record["base_commit"])
            or str(repo.common_dir) != record["common_dir"]
            or repo.branch() != record["branch"]
            or parent != review["base_commit"]
            or record["branch"] in {*body.protected_branches, "main", "master"}
        ):
            raise ValueError("Reviewed worktree or parent changed")
        if repo.read(["diff", "--cached", "--quiet"], check=False).returncode != 0:
            raise ValueError("Worktree index changed; inspect staged changes before committing")
        files = read_review_files(workspace, [item["path"] for item in review["files"]])
        for actual, expected in zip(files, review["files"], strict=True):
            deleted = expected.get("operation") == "delete"
            if (deleted and (expected["after_sha256"] is not None or actual["content"] is not None)) or (
                not deleted and (actual["content"] is None or actual["sha256"] != expected["after_sha256"])
            ):
                raise ValueError("Reviewed file changed; request a new review")
        env = {
            **git_environment(),
            "GIT_INDEX_FILE": str(root / "index"),
            "GIT_AUTHOR_NAME": "AI Station",
            "GIT_AUTHOR_EMAIL": "ai-station@localhost",
            "GIT_COMMITTER_NAME": "AI Station",
            "GIT_COMMITTER_EMAIL": "ai-station@localhost",
        }

        def git(*args):
            result = subprocess.run(
                [
                    "git",
                    *BASE_CONFIG,
                    *repo.options,
                    "-c",
                    "commit.gpgSign=false",
                    "-c",
                    "core.splitIndex=false",
                    "-c",
                    "core.sparseCheckout=false",
                    "-C",
                    str(workspace),
                    *args,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            return result.stdout.strip()

        git("read-tree", parent)
        for index, (actual, expected) in enumerate(zip(files, review["files"], strict=True)):
            entry = repo.read(["ls-tree", parent, "--", actual["path"]]).stdout
            if expected.get("operation") == "delete":
                if not entry or entry.split()[0] not in {"100644", "100755"}:
                    raise ValueError("Reviewed deletion requires an ordinary tracked source file")
                original = repo.read(["show", f"{parent}:{actual['path']}"]).stdout
                if hashlib.sha256(original.encode()).hexdigest() != expected["before_sha256"]:
                    raise ValueError("Reviewed deletion source changed; request a new review")
                git("update-index", "--force-remove", "--", actual["path"])
                continue
            mode = entry.split()[0] if entry else "100644"
            if mode not in {"100644", "100755"} or bool(actual["mode"] & 0o111) != (mode == "100755"):
                raise ValueError("Reviewed file mode changed")
            snapshot = root / f"file-{index}"
            with snapshot.open("x", encoding="utf-8", newline="") as handle:
                handle.write(actual["content"])
            blob = git("hash-object", "-w", "--no-filters", "--", str(snapshot))
            git("update-index", "--add", "--cacheinfo", mode, blob, actual["path"])
        tree = git("write-tree")
        if tree == repo.read(["rev-parse", parent + "^{tree}"]).stdout.strip():
            raise ValueError("Review contains no changes to commit")
        commit = git("commit-tree", tree, "-p", parent, "-m", body.message)
        # Publish only on the exact owned task ref and expected parent.
        git("update-ref", f"refs/heads/{record['branch']}", commit, parent)
        record["head_commit"] = commit
        save_manifest(record)
        env.pop("GIT_INDEX_FILE")
        git("read-tree", commit)
        report = {
            "run_id": run_id,
            "source_run_id": str(body.source_run_id),
            "project_id": str(body.project_id),
            "worktree_run_id": record["run_id"],
            "branch": record["branch"],
            "parent": parent,
            "commit": commit,
            "files": [item["path"] for item in files],
            "message": body.message,
        }
        with (root / "report.json").open("x") as handle:
            json.dump(report, handle)
        print(f"Created reviewed commit {commit} on {record['branch']}", flush=True)


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
