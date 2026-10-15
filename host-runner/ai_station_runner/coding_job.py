"""Shared selected-file proposal application for native coding providers."""

import fcntl
import os

from ai_station_runner.coding_files import apply_proposal, parse_proposal, read_review_files, read_selected
from ai_station_runner.coding_review import checked_report_bytes, projected_review
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
    local_context = location == "local"  # Native adapter policy, never model-controlled.
    exploration = []
    if discover is not None:
        selected, exploration = discover(workspace)
    else:
        selected = read_selected(workspace, body.files, local_context=local_context)
    print(f"{location.upper()} proposal for {len(selected)} selected files; tools disabled", flush=True)
    text, provider = generate(selected)
    proposal = parse_proposal(text, selected, local_context=local_context)
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
    cumulative = bool(getattr(body, "cumulative", False))
    repair = bool(getattr(body, "repair_source_run_id", None))
    changes, snapshots = projected_review(
        repo, workspace, selected, proposal, cumulative=cumulative, repair=repair
    )
    report = {"summary": proposal["summary"], "files": changes, "review_status": "needs_review"}
    if cumulative or repair:
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
    if local_context:
        report["source_context"] = {
            "policy": "local-bounded",
            "files": len(selected),
            "bytes": sum(len((item["content"] or "").encode()) for item in selected),
        }
    if exploration:
        report["exploration"] = exploration
    encoded = checked_report_bytes(report)  # Reject oversized results before any proposal write.
    if read_review_files(workspace, [item["path"] for item in snapshots]) != snapshots:
        raise ValueError("Review files changed before proposal application")
    if (
        repo.read(["rev-parse", "HEAD"]).stdout.strip() != report["base_commit"]
        or repo.branch() != record["branch"]
    ):
        raise ValueError("Worktree changed before proposal application")
    apply_proposal(workspace, selected, proposal, local_context=local_context)
    path = root / "report.json"
    with path.open("xb") as handle:
        os.chmod(path, 0o600)
        handle.write(encoded)
    print(
        f"Applied {len(report['files'])} file replacements; review and validation still required", flush=True
    )
