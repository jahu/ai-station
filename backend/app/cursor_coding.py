"""Explicit external Cursor tasks, fresh worktrees and ordinary follow-up Runs."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import Run, Worktree
from app.projects import get_project
from app.runs import create_run, create_task, run_dict
from app.state import TERMINAL

router = APIRouter(prefix="/api/coding", tags=["coding"])


class CursorTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    expected_updated_at: datetime
    prompt: str = Field(min_length=1, max_length=10000)
    files: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(min_length=1, max_length=10)
    model: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._:/ -]*$")
    external_ai: Literal[True]

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Describe the coding task")
        return value.strip()


@router.post("/cursor", status_code=202)
def create_cursor_task(body: CursorTask, session: Annotated[Session, Depends(session_scope)]):
    project = get_project(session, body.project_id)
    if project.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Project settings changed. Reload before starting a coding task.")
    if session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "This project already has an active Run")
    task = create_task(
        session,
        title=body.prompt[:200],
        prompt=body.prompt,
        capability="coding.cursor",
        project_id=project.id,
    )
    request = {
        "prompt": body.prompt,
        "files": body.files,
        "model": body.model,
        "guidance": project.agent_rules,
        "commands": [
            {"kind": kind, "argv": argv}
            for kind, commands in (
                ("test", project.test_commands),
                ("lint", project.lint_commands),
                ("build", project.build_commands),
            )
            for argv in commands
        ],
    }
    run = create_run(
        session,
        task,
        run_type="worktree",
        capability="coding.prepare",
        executor_type="worktree_prepare",
        execution_target="host",
        permissions=["filesystem_read", "workspace_write", "git_read", "git_write"],
        retry_class="inspect",
        parameters={
            "repo_path": project.repo_path,
            "base_branch": project.integration_branch,
            "cursor": request,
        },
    )
    branch = f"ai/{run.id}-workspace"
    relative = f"worktrees/{project.id}/{run.id}"
    session.add(
        Worktree(
            project_id=project.id,
            run_id=run.id,
            relative_path=relative,
            branch=branch,
            base_branch=project.integration_branch,
            owned=False,
        )
    )
    run.metadata_json = {
        "relative_path": relative,
        "branch": branch,
        "next_executor": "cursor_proposal",
        "execution_location": "external",
    }
    session.commit()
    return run_dict(run)


def queue_cursor(session, preparation, worktree):
    request = preparation.parameters.get("cursor")
    if not request:
        return
    run = create_run(
        session,
        preparation.task,
        run_type="coding",
        capability="coding.cursor",
        executor_type="cursor_proposal",
        execution_target="host",
        permissions=["filesystem_read", "workspace_write", "git_read", "external_ai"],
        retry_class="inspect",
        parameters={**request, "worktree_id": worktree.id, "worktree_run_id": preparation.id},
    )
    run.parent_run_id = preparation.id
    run.metadata_json = {"execution_location": "external", "worktree": preparation.metadata_json["worktree"]}
    preparation.metadata_json = {**preparation.metadata_json, "coding_run_id": run.id}
    preparation.summary = f"Prepared {worktree.branch}; external Cursor proposal queued."


def queue_validation(session, coding_run):
    commands = coding_run.parameters["commands"]
    if not commands:
        coding_run.metadata_json = {**coding_run.metadata_json, "validation_status": "not_configured"}
        return
    run = create_run(
        session,
        coding_run.task,
        run_type="validation",
        capability="coding.validate",
        executor_type="project_validation",
        execution_target="host",
        permissions=["filesystem_read", "workspace_write", "git_read", "shell_project_commands"],
        retry_class="inspect",
        parameters={
            "worktree_id": coding_run.parameters["worktree_id"],
            "worktree_run_id": coding_run.parameters["worktree_run_id"],
            "commands": commands,
        },
    )
    run.parent_run_id = coding_run.id
    coding_run.metadata_json = {
        **coding_run.metadata_json,
        "validation_run_id": run.id,
        "validation_status": "queued",
    }
