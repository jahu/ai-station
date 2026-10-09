"""Inspect GitHub after an uncertain publication. Never pushes."""

from __future__ import annotations

import fcntl
import json
import os
import sys
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.config import get_settings
from ai_station_runner.gitinspect import git_environment
from ai_station_runner.gitops import GitError
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.publication import load_request
from ai_station_runner.worktrees import owned_path

PERMISSIONS = {"filesystem_read", "git_read", "network_external"}


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    publication_run_id: UUID
    project_id: UUID
    permissions: list[str] = Field(max_length=3)


def directory(run_id):
    return owned_path(f"runtime/publication-reconcile-runs/{UUID(run_id)}")


def load_reconcile(run_id):
    path = directory(run_id) / "request.json"
    if path.stat().st_size > 16384:
        raise GitError("Publication reconcile request exceeds limit")
    value = json.loads(path.read_text())
    body = ReconcileRequest.model_validate(value["request"])
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise GitError("Publication reconcile ownership or permissions changed")
    return body


def start_reconcile(manager, body: ReconcileRequest):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Publication reconcile requires Git read and network access, not push")
    run_id = str(body.run_id)
    root = directory(run_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        os.chmod(root / "request.lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "request.json"
        if path.exists():
            if load_reconcile(run_id) != body:
                raise GitError("Run owns another publication reconcile request")
            try:
                process = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise GitError("Uncertain publication reconcile requires inspection") from exc
            if process["executor"] != "publication_reconcile":
                raise GitError("Run belongs to another executor")
            return process
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise GitError("Run already owns a process")
        publication, _ = load_request(str(body.publication_run_id))
        if str(publication.project_id) != str(body.project_id):
            raise GitError("Publication ownership does not match this reconcile request")
        with path.open("x") as handle:
            os.chmod(path, 0o600)
            json.dump({"request": body.model_dump(mode="json")}, handle)
        settings = get_settings()
        env = {
            **git_environment(),
            "PYTHONPATH": os.pathsep.join(sys.path),
            "PYTHONUNBUFFERED": "1",
            "AI_STATION_DATA_HOST_PATH": str(settings.host_data_dir().resolve()),
            "AI_STATION_ALLOWED_ROOTS": ":".join(str(p.resolve()) for p in settings.roots()),
            "AI_STATION_MODEL_ROOTS": "",
        }
        return manager.start(
            run_id=run_id,
            argv=[sys.executable, "-m", "ai_station_runner.publication_reconcile_job", run_id],
            cwd=root,
            executor="publication_reconcile",
            env=env,
        )


def reconcile_report(manager, run_id):
    body = load_reconcile(run_id)
    process = manager.inspect(run_id)
    if (
        process["executor"] != "publication_reconcile"
        or process["alive"]
        or process.get("completion_pending")
        or process.get("exit_code") != 0
        or process["status"] in {"canceled", "interrupted"}
    ):
        raise GitError("Publication reconcile has no confirmed successful completion")
    path = directory(run_id) / "report.json"
    if path.stat().st_size > 32000:
        raise GitError("Publication reconcile report exceeds limit")
    report = json.loads(path.read_text())
    if report["run_id"] != run_id or report["publication_run_id"] != str(body.publication_run_id):
        raise GitError("Publication reconcile report ownership changed")
    return report
