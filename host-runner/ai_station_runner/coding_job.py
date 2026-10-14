"""Shared selected-file proposal application for native coding providers."""

import fcntl
import hashlib
import json
import os

from ai_station_runner.coding_files import apply_proposal, describe_change, parse_proposal, read_selected
from ai_station_runner.gitinspect import Repository
from ai_station_runner.worktrees import load_manifest, owned_path


def execute_proposal(run_id, body, root, generate, *, location, discover=None):
    if os.getpgrp() != os.getpid():
        raise RuntimeError("Coding execution requires an owned process group")
    record = load_manifest(str(body.worktree_run_id))
    workspace = owned_path(record["relative_path"])
    repo = Repository(workspace, shared_group=True)
    if (
        record["state"] != "ready"
        or record["project_id"] != str(body.project_id)
        or str(repo.common_dir) != record["common_dir"]
        or repo.branch() != record["branch"]
        or repo.read(["rev-parse", "HEAD"]).stdout.strip() != record.get("head_commit", record["base_commit"])
    ):
        raise ValueError("Worktree ownership changed")
    lock_path = owned_path(f"runtime/validation-worktrees/{body.worktree_run_id}.lock")
    lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = lock_path.open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    exploration = []
    if discover is not None:
        selected, exploration = discover(workspace)
    else:
        selected = read_selected(workspace, body.files)
    print(f"{location.upper()} proposal for {len(selected)} selected files; tools disabled", flush=True)
    text, provider = generate(selected)
    proposal = parse_proposal(text, selected)
    if getattr(body, "repair_source_run_id", None) and any(
        item["content"] is None for item in proposal["files"]
    ):
        raise ValueError("Repair cannot delete selected source files")
    # Recheck repository identity as well as every source file after inference.
    current = Repository(workspace, shared_group=True)
    if (
        current.common_dir != repo.common_dir
        or current.branch() != record["branch"]
        or current.read(["rev-parse", "HEAD"]).stdout.strip()
        != record.get("head_commit", record["base_commit"])
    ):
        raise ValueError("Worktree changed during inference")
    cumulative = getattr(body, "cumulative", False)
    review_paths = [item["path"] for item in selected]
    if cumulative:
        dirty = repo.read(["diff", "--name-only", "-z", "HEAD"]).stdout
        dirty += repo.read(["ls-files", "--others", "--exclude-standard", "-z"]).stdout
        review_paths = list(dict.fromkeys([*review_paths, *filter(None, dirty.split("\0"))]))
        read_selected(workspace, review_paths)  # Bound cumulative review before writing.
    report = apply_proposal(workspace, selected, proposal)
    if cumulative or getattr(body, "repair_source_run_id", None):
        # Compare every scoped file with the task HEAD, so accepting a repair
        # commits the complete reviewed result, including earlier replacements.
        changes = []
        for item in read_selected(workspace, review_paths):
            blob = repo.read(["show", f"HEAD:{item['path']}"], check=False)
            original = {**item, "content": None, "sha256": None}
            if blob.returncode == 0:
                mode = repo.read(["ls-tree", "HEAD", "--", item["path"]]).stdout.split()[0]
                if mode not in {"100644", "100755"}:
                    raise ValueError("Cumulative review requires ordinary source files")
                original["content"] = blob.stdout
                original["sha256"] = hashlib.sha256(blob.stdout.encode()).hexdigest()
                original["mode"] = int(mode, 8) & 0o777
            elif repo.read(["ls-tree", "HEAD", "--", item["path"]]).stdout:
                raise ValueError("Could not read the task base for repair review")
            if original["content"] != item["content"]:
                changes.append(describe_change(original, item))
        report["files"] = changes
        report["repair_source_run_id"] = str(getattr(body, "repair_source_run_id", ""))
    report.update(
        run_id=run_id,
        project_id=str(body.project_id),
        worktree_run_id=str(body.worktree_run_id),
        branch=record["branch"],
        base_commit=record.get("head_commit", record["base_commit"]),
        provider=provider,
        execution_location=location,
    )
    if exploration:
        report["exploration"] = exploration
    path = root / "report.json"
    with path.open("x") as handle:
        os.chmod(path, 0o600)
        json.dump(report, handle)
    print(
        f"Applied {len(report['files'])} file replacements; review and validation still required", flush=True
    )
