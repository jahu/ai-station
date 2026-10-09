"""Unused owned worktrees expire through the existing removal Run."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Project, Run, Worktree
from app.runs import create_run, create_task
from app.state import TERMINAL

TTL = timedelta(days=7)


def schedule_expiry(worktree: Worktree) -> None:
    if worktree.removed_at is not None or not worktree.owned:
        return
    worktree.expires_at = utcnow() + TTL


def pin_expiry(worktree: Worktree) -> None:
    if worktree.removed_at is not None:
        return
    worktree.expires_at = None


def refresh_expiry(session: Session, *, worktree_id=None, worktree_run_id=None) -> None:
    if worktree_id:
        worktree = session.get(Worktree, str(worktree_id))
    elif worktree_run_id:
        worktree = session.scalar(select(Worktree).where(Worktree.run_id == str(worktree_run_id)))
    else:
        return
    if worktree is None or worktree.expires_at is None:
        return
    schedule_expiry(worktree)


def queue_worktree_removal(
    session: Session, project: Project, worktree: Worktree, *, triggered_by: str
) -> Run:
    expected = f"worktrees/{project.id}/{worktree.run_id}"
    if worktree.removed_at is not None:
        raise ValueError("This worktree was already removed")
    if worktree.relative_path != expected or worktree.branch != f"ai/{worktree.run_id}-workspace":
        raise ValueError("Worktree ownership record is inconsistent")
    if session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise ValueError("This project already has an active Run")
    title = (
        f"Expire unused worktree for {project.name}"
        if triggered_by == "scheduler"
        else f"Remove worktree for {project.name}"
    )
    task = create_task(
        session,
        title=title,
        prompt="Remove an owned local Git worktree",
        capability="coding.worktree.remove",
        project_id=project.id,
    )
    run = create_run(
        session,
        task,
        run_type="worktree",
        capability="coding.worktree.remove",
        executor_type="worktree_remove",
        execution_target="host",
        permissions=["filesystem_read", "workspace_write", "git_read", "git_write"],
        retry_class="inspect",
        triggered_by=triggered_by,
        parameters={
            "worktree_id": worktree.id,
            "worktree_run_id": worktree.run_id,
            "repo_path": project.repo_path,
            "relative_path": worktree.relative_path,
            "branch": worktree.branch,
        },
    )
    run.parent_run_id = worktree.run_id
    return run


def expire_due_worktrees(session: Session, *, limit: int = 1) -> list[str]:
    created = []
    now = utcnow()
    rows = list(
        session.scalars(
            select(Worktree)
            .where(
                Worktree.owned.is_(True),
                Worktree.removed_at.is_(None),
                Worktree.expires_at.is_not(None),
                Worktree.expires_at <= now,
            )
            .order_by(Worktree.expires_at, Worktree.id)
            .limit(20)
        )
    )
    for worktree in rows:
        if len(created) >= limit:
            break
        project = session.get(Project, worktree.project_id)
        if project is None:
            continue
        try:
            with session.begin_nested():
                run = queue_worktree_removal(session, project, worktree, triggered_by="scheduler")
            created.append(run.id)
        except ValueError:
            continue
    return created
