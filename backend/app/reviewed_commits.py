"""Explicit acceptance of a persisted coding review, with no push or merge."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.gitpolicy import GitPolicyError, assert_branch_allowed, normalize_policy
from app.models import Project, Run
from app.runs import create_run, run_dict
from app.state import TERMINAL

router = APIRouter(prefix="/api/coding")


class ReviewedCommit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)
    reviewed: Literal[True]


def enqueue_reviewed_commit(session, source, body: ReviewedCommit):
    review = source.metadata_json.get("coding_review")
    if (
        source.status != "succeeded"
        or source.executor_type not in {"cursor_proposal", "codex_proposal", "local_proposal"}
        or not review
        or not review.get("files")
    ):
        raise HTTPException(409, "A completed proposal with reviewed changes is required")
    if source.metadata_json.get("repair_run_id") or source.metadata_json.get("continuation_run_id"):
        raise HTTPException(409, "This proposal was superseded by further work; review the latest Run")
    if source.metadata_json.get("commit_run_id"):
        raise HTTPException(409, "A commit was already requested; inspect that Run")
    project = session.get(Project, source.project_id)
    if project is None or not normalize_policy(project.pr_policy)["commit_task_branch"]:
        raise HTTPException(403, "Project policy does not allow task-branch commits")
    try:
        assert_branch_allowed(review["branch"], project.protected_branches, action="commit")
    except GitPolicyError as exc:
        raise HTTPException(403, str(exc)) from exc
    validation_id = source.metadata_json.get("validation_run_id")
    validation = session.get(Run, validation_id) if validation_id else None
    plan_id = source.metadata_json.get("project_plan_run_id")
    if plan_id:
        plan = session.get(Run, plan_id)
        if not plan or plan.status != "succeeded":
            raise HTTPException(409, "Automatic project preparation must succeed before committing")
        for dep_id in source.metadata_json.get("dependency_run_ids", []):
            dependency = session.get(Run, dep_id)
            if not dependency or dependency.status != "succeeded":
                raise HTTPException(409, "Project dependencies must succeed before committing")
    if (source.parameters.get("commands") or source.metadata_json.get("automatic_commands")) and (
        validation is None or validation.status != "succeeded"
    ):
        raise HTTPException(409, "Configured validation must pass before committing")
    if session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "This project has an active Run")
    run = create_run(
        session,
        source.task,
        run_type="git",
        capability="coding.commit",
        executor_type="reviewed_commit",
        project_id=project.id,
        parent_run_id=source.id,
        permissions=["filesystem_read", "git_read", "git_write"],
        retry_class="inspect",
        parameters={
            "source_run_id": source.id,
            "worktree_run_id": source.parameters["worktree_run_id"],
            "review_digest": hashlib.sha256(
                json.dumps(review, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "message": body.message,
            "protected_branches": project.protected_branches,
        },
    )
    source.metadata_json = {**source.metadata_json, "commit_run_id": run.id}
    return run


@router.post("/runs/{source_id}/commit", status_code=202)
def enqueue(source_id: UUID, body: ReviewedCommit, session: Annotated[Session, Depends(session_scope)]):
    source = session.get(Run, str(source_id))
    if source is None:
        raise HTTPException(404, "Coding Run not found")
    run = enqueue_reviewed_commit(session, source, body)
    session.commit()
    return run_dict(run)
