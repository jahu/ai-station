"""Keep owned worktrees until the user explicitly requests removal."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Project, Run, Worktree
from app.project_activity import project_write_condition
from app.runs import create_run, create_task
from app.state import TERMINAL


def schedule_expiry(worktree: Worktree) -> None:
    if worktree.removed_at is not None or not worktree.owned:
        return
    worktree.expires_at = None


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
    if triggered_by != "user":
        raise ValueError("Worktree removal requires an explicit user request")
    if not worktree.owned:
        raise ValueError("Only an owned worktree can be removed")
    expected = f"worktrees/{project.id}/{worktree.run_id}"
    if worktree.removed_at is not None:
        raise ValueError("This worktree was already removed")
    if worktree.relative_path != expected or worktree.branch != f"ai/{worktree.run_id}-workspace":
        raise ValueError("Worktree ownership record is inconsistent")
    if session.scalar(
        select(Run.id)
        .where(Run.project_id == project.id, Run.status.not_in(TERMINAL), project_write_condition())
        .limit(1)
    ):
        raise ValueError("This project already has an active Run")
    task = create_task(
        session,
        title=f"Remove worktree for {project.name}",
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


def expire_due_worktrees(session: Session) -> list[str]:
    """Disarm legacy deadlines without queuing any destructive work.

    Inactivity does not establish that changes are committed, merged or disposable.
    Keep this scheduler hook so upgrades also clear deadlines saved by older versions.
    """
    session.execute(
        update(Worktree)
        .where(Worktree.owned.is_(True), Worktree.removed_at.is_(None), Worktree.expires_at.is_not(None))
        .values(expires_at=None)
    )
    return []
