"""Shared fresh-worktree, proposal and validation workflow for coding providers."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy import select

from app.models import Run, Worktree
from app.projects import get_project
from app.runs import create_run, create_task
from app.state import TERMINAL


class CodingTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    expected_updated_at: datetime
    prompt: str = Field(min_length=1, max_length=10000)
    files: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=10
    )
    explore: StrictBool = False
    model: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._:/ -]*$")

    @model_validator(mode="after")
    def selection(self):
        if self.explore and self.files or not self.explore and not self.files:
            raise ValueError("Choose automatic file discovery or explicit source files")
        return self

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Describe the coding task")
        return value.strip()


def enqueue_coding_task(session, body, *, provider="cursor", task=None, parent_run_id=None):
    local = provider == "local"
    if provider not in {"cursor", "codex", "local"}:
        raise ValueError("Unsupported coding provider")
    project = get_project(session, body.project_id)
    if project.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Project settings changed. Reload before starting a coding task.")
    if session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "This project already has an active Run")
    task = task or create_task(
        session,
        title=body.prompt[:200],
        prompt=body.prompt,
        capability=f"coding.{provider}",
        project_id=project.id,
    )
    task.project_id = project.id
    request = {
        "prompt": body.prompt,
        "files": body.files,
        "explore": body.explore,
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
    if local:
        from app.local_provider import model_endpoint

        request["endpoint"] = model_endpoint(body.model, session)
        request["explore"] = body.explore
        request["max_repair_attempts"] = body.max_repair_attempts
    run = create_run(
        session,
        task,
        run_type="worktree",
        project_id=project.id,
        parent_run_id=parent_run_id,
        capability="coding.prepare",
        executor_type="worktree_prepare",
        execution_target="host",
        permissions=["filesystem_read", "workspace_write", "git_read", "git_write"],
        retry_class="inspect",
        parameters={
            "repo_path": project.repo_path,
            "base_branch": project.integration_branch,
            "local_coding" if local else provider: request,
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
        "next_executor": "local_proposal" if local else f"{provider}_proposal",
        "execution_location": "local" if local else "external",
    }
    return run


def queue_proposal(session, preparation, worktree):
    local = "local_coding" in preparation.parameters
    provider = "local" if local else "codex" if "codex" in preparation.parameters else "cursor"
    request = preparation.parameters.get("local_coding" if local else provider)
    if not request:
        return
    run = create_run(
        session,
        preparation.task,
        run_type="coding",
        project_id=preparation.project_id,
        capability=f"coding.{provider}",
        executor_type="local_proposal" if local else f"{provider}_proposal",
        execution_target="host",
        permissions=[
            "filesystem_read",
            "workspace_write",
            "git_read",
            "network_read" if local else "external_ai",
        ],
        retry_class="inspect",
        parameters={**request, "worktree_id": worktree.id, "worktree_run_id": preparation.id},
    )
    if local:
        from app.llama import prepare_consumer

        prepare_consumer(session, run)
    run.parent_run_id = preparation.id
    run.metadata_json = {
        "execution_location": "local" if local else "external",
        "worktree": preparation.metadata_json["worktree"],
    }
    preparation.metadata_json = {**preparation.metadata_json, "coding_run_id": run.id}
    preparation.summary = f"Prepared {worktree.branch}; {'Local AI' if local else 'External ' + provider.title()} proposal queued."


def queue_validation(session, coding_run):
    commands = coding_run.parameters["commands"]
    if not commands:
        coding_run.metadata_json = {**coding_run.metadata_json, "validation_status": "not_configured"}
        return
    run = create_run(
        session,
        coding_run.task,
        run_type="validation",
        project_id=coding_run.project_id,
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
