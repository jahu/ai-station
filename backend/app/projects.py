"""Persistent project configuration; host inspection stays behind the runner."""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.models import Project, Run
from app.runner_client import RunnerClient, RunnerError
from app.serialize import project_dict
from app.state import TERMINAL

router = APIRouter(prefix="/api/projects", tags=["projects"])
DB = Annotated[Session, Depends(session_scope)]
Argument = Annotated[str, Field(min_length=1, max_length=4096)]
Command = Annotated[list[Argument], Field(min_length=1, max_length=64)]
Commands = Annotated[list[Command], Field(max_length=20)]


class PRPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commit_task_branch: StrictBool = True
    push_task_branch: StrictBool = False
    pr_to_integration: StrictBool = False
    pr_to_production: Literal[False] = False
    automatic_merge: Literal[False] = False
    force_push: Literal[False] = False


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    default_branch: str = Field(default="main", min_length=1, max_length=200)
    integration_branch: str = Field(default="develop", min_length=1, max_length=200)
    protected_branches: list[str] = Field(default_factory=lambda: ["main", "master"], max_length=50)
    preferred_executor: Literal["codex", "cursor", "claude", "local"] = "codex"
    test_commands: Commands = Field(default_factory=list)
    lint_commands: Commands = Field(default_factory=list)
    build_commands: Commands = Field(default_factory=list)
    agent_rules: str = Field(default="", max_length=32000)
    pr_policy: PRPolicy = Field(default_factory=PRPolicy)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Project name must contain readable text")
        return value

    @model_validator(mode="after")
    def validate_configuration(self):
        for branch in [self.default_branch, self.integration_branch, *self.protected_branches]:
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch)
                or ".." in branch
                or branch == "HEAD"
                or any(
                    not part or part.startswith(".") or part.endswith((".", ".lock"))
                    for part in branch.split("/")
                )
            ):
                raise ValueError("Use simple Git branch names, not options or revision expressions")
        self.protected_branches = sorted({"main", "master", self.default_branch, *self.protected_branches})
        if len(self.protected_branches) > 50:
            raise ValueError("At most 50 protected branches, including mandatory protections, are allowed")
        size = 0
        for command in self.test_commands + self.lint_commands + self.build_commands:
            if not command[0].strip() or command[0].startswith("-"):
                raise ValueError("Each command needs an executable as its first argument")
            for argument in command:
                if any(ord(char) < 32 for char in argument):
                    raise ValueError("Command arguments cannot contain control characters")
                size += len(argument)
        if size > 32000:
            raise ValueError("Configured commands exceed the 32,000 character limit")
        return self


class ProjectCreate(ProjectSettings):
    repo_path: str = Field(min_length=1, max_length=4096)

    @field_validator("repo_path")
    @classmethod
    def host_path(cls, value):
        if not value.startswith(("/", "~/")) or any(ord(char) < 32 for char in value):
            raise ValueError("Use an absolute host path or a path beginning with ~/")
        return value


class ProjectUpdate(ProjectSettings):
    expected_updated_at: datetime


def get_project(session: Session, project_id: UUID) -> Project:
    project = session.get(Project, str(project_id))
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def inspect_repository(path: str) -> dict:
    try:
        return RunnerClient().validate_project(path)
    except RunnerError as exc:
        if exc.status_code in {400, 403, 404, 422}:
            raise HTTPException(422, exc.detail) from exc
        raise


@router.get("")
def projects(session: DB, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    rows = session.scalars(select(Project).order_by(Project.name, Project.id).limit(limit).offset(offset))
    return [project_dict(row) for row in rows]


@router.post("", status_code=201)
def register_project(body: ProjectCreate, session: DB):
    # No database reservation while the native runner validates the host path.
    info = inspect_repository(body.repo_path)
    path = info["repo_path"]
    if len(path) > 1000:
        raise HTTPException(422, "Canonical repository path exceeds the 1,000 character storage limit")
    if session.scalar(select(Project.id).where(Project.repo_path == path)):
        raise HTTPException(409, "This repository is already registered")
    values = body.model_dump(exclude={"repo_path"})
    project = Project(repo_path=path, **values)
    session.add(project)
    session.commit()
    return project_dict(project)


@router.get("/{project_id}")
def project_detail(project_id: UUID, session: DB):
    return project_dict(get_project(session, project_id))


@router.put("/{project_id}")
def update_project(project_id: UUID, body: ProjectUpdate, session: DB):
    project = get_project(session, project_id)
    if body.expected_updated_at != project.updated_at:
        raise HTTPException(409, "Project settings changed. Reload before saving again.")
    active = session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    )
    if active:
        raise HTTPException(409, "Project settings cannot change while a project Run is active")
    for key, value in body.model_dump(exclude={"expected_updated_at"}).items():
        setattr(project, key, value)
    project.updated_at = utcnow()
    session.commit()
    return project_dict(project)


@router.get("/{project_id}/status")
def project_status(project_id: UUID, session: DB):
    path = get_project(session, project_id).repo_path
    session.rollback()
    info = inspect_repository(path)
    if info["repo_path"] != path:
        raise HTTPException(409, "Repository location changed; inspect the registered host path")
    state = RunnerClient().git_status(path)
    return {**state, "repo_path": path, "checked_at": utcnow().isoformat()}
