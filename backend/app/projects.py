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
from app.models import Project, Run, Worktree
from app.runner_client import RunnerClient, RunnerError
from app.runs import create_run, create_task, run_dict
from app.serialize import project_dict, worktree_dict
from app.state import TERMINAL
from app.validation_environment import ValidationEnvironment
from app.worktree_expiry import pin_expiry, queue_worktree_removal, refresh_expiry

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
    auto_install_dependencies: StrictBool = False
    auto_validate: StrictBool = False
    validation_environment: ValidationEnvironment | None = None
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
        if key == "validation_environment" and key not in body.model_fields_set:
            continue
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


class WorktreeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime


@router.post("/{project_id}/worktrees", status_code=202)
def prepare_project_worktree(project_id: UUID, body: WorktreeRequest, session: DB):
    project = get_project(session, project_id)
    if project.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Project settings changed. Reload before preparing a worktree.")
    if session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "This project already has an active Run")
    task = create_task(
        session,
        title=f"Prepare worktree for {project.name}",
        prompt="Prepare an isolated local Git worktree",
        capability="coding.prepare",
        project_id=project.id,
    )
    run = create_run(
        session,
        task,
        run_type="worktree",
        capability="coding.prepare",
        executor_type="worktree_prepare",
        execution_target="host",
        permissions=["filesystem_read", "workspace_write", "git_read", "git_write"],
        retry_class="inspect",
        parameters={"repo_path": project.repo_path, "base_branch": project.integration_branch},
    )
    relative = f"worktrees/{project.id}/{run.id}"
    branch = f"ai/{run.id}-workspace"
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
    run.metadata_json = {"relative_path": relative, "branch": branch}
    session.commit()
    return run_dict(run)


@router.get("/{project_id}/worktrees")
def project_worktrees(project_id: UUID, session: DB):
    get_project(session, project_id)
    rows = session.execute(
        select(Worktree, Run.status)
        .outerjoin(Run, Run.id == Worktree.run_id)
        .where(Worktree.project_id == str(project_id))
        .order_by(Worktree.created_at.desc())
        .limit(100)
    )
    return [{**worktree_dict(row), "run_status": status} for row, status in rows]


@router.post("/{project_id}/worktrees/{worktree_id}/validate", status_code=202)
def validate_project_worktree(project_id: UUID, worktree_id: UUID, body: WorktreeRequest, session: DB):
    project = get_project(session, project_id)
    if project.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Project settings changed. Reload before validation.")
    worktree = session.get(Worktree, str(worktree_id))
    if worktree is None or worktree.project_id != project.id:
        raise HTTPException(404, "Worktree not found in this project")
    preparation = session.get(Run, worktree.run_id)
    if (
        worktree.removed_at is not None
        or not worktree.owned
        or preparation is None
        or preparation.status != "succeeded"
    ):
        raise HTTPException(409, "Worktree preparation must have succeeded")
    if session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "This project already has an active Run")
    commands = [
        {"kind": kind, "argv": argv}
        for kind, group in (
            ("test", project.test_commands),
            ("lint", project.lint_commands),
            ("build", project.build_commands),
        )
        for argv in group
    ]
    if not commands:
        raise HTTPException(422, "Save test, lint or build commands in project settings first")
    task = create_task(
        session,
        title=f"Validate {project.name}",
        prompt="Run saved project validation in an owned worktree",
        capability="coding.validate",
        project_id=project.id,
    )
    run = create_run(
        session,
        task,
        run_type="validation",
        capability="coding.validate",
        executor_type="project_validation",
        execution_target="host",
        permissions=["filesystem_read", "workspace_write", "git_read", "shell_project_commands"],
        retry_class="inspect",
        parameters={
            "worktree_id": worktree.id,
            "worktree_run_id": worktree.run_id,
            "commands": commands,
            "project_updated_at": project.updated_at.isoformat(),
            **(
                {"validation_environment": project.validation_environment}
                if project.validation_environment
                else {}
            ),
        },
    )
    run.parent_run_id = worktree.run_id
    refresh_expiry(session, worktree_id=worktree.id)
    session.commit()
    return run_dict(run)


@router.post("/{project_id}/worktrees/{worktree_id}/dependencies", status_code=202)
def install_project_dependencies(project_id: UUID, worktree_id: UUID, body: WorktreeRequest, session: DB):
    project = get_project(session, project_id)
    if project.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Project settings changed. Reload before installing dependencies.")
    worktree = session.get(Worktree, str(worktree_id))
    if worktree is None or worktree.project_id != project.id:
        raise HTTPException(404, "Worktree not found in this project")
    preparation = session.get(Run, worktree.run_id)
    if (
        worktree.removed_at is not None
        or not worktree.owned
        or preparation is None
        or preparation.status != "succeeded"
    ):
        raise HTTPException(409, "Worktree preparation must have succeeded")
    if session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "This project already has an active Run")
    task = create_task(
        session,
        title=f"Install dependencies for {project.name}",
        prompt="Install declared Python dependencies in an owned worktree",
        capability="coding.dependencies",
        project_id=project.id,
    )
    run = create_run(
        session,
        task,
        run_type="dependencies",
        capability="coding.dependencies",
        executor_type="project_dependencies",
        execution_target="host",
        permissions=[
            "filesystem_read",
            "workspace_write",
            "git_read",
            "shell_project_commands",
            "network_read",
        ],
        retry_class="inspect",
        parameters={
            "worktree_id": worktree.id,
            "worktree_run_id": worktree.run_id,
            "project_updated_at": project.updated_at.isoformat(),
            **(
                {"validation_environment": project.validation_environment}
                if project.validation_environment
                else {}
            ),
        },
    )
    run.parent_run_id = worktree.run_id
    environment = project.validation_environment
    if environment:
        selected = ValidationEnvironment.model_validate(environment)
        run.parameters = {
            **run.parameters,
            "ecosystem": "python" if selected.python_manifest else "auto",
            **({"python_manifest": selected.python_manifest} if selected.python_manifest else {}),
        }
        if selected.node_directory:
            node_parameters = {
                key: value for key, value in run.parameters.items() if key != "python_manifest"
            }
            node_parameters.update(ecosystem="node", directory=selected.node_directory)
            if not selected.python_manifest and not selected.python_source_roots:
                run.parameters = node_parameters
            else:
                from app.dependencies import depend_on

                node_run = create_run(
                    session,
                    task,
                    run_type="dependencies",
                    capability="coding.dependencies",
                    executor_type="project_dependencies",
                    execution_target="host",
                    permissions=run.effective_permissions,
                    retry_class="inspect",
                    parameters=node_parameters,
                    parent_run_id=run.id,
                )
                depend_on(session, node_run, run)
                run.metadata_json = {**run.metadata_json, "node_dependency_run_id": node_run.id}
    refresh_expiry(session, worktree_id=worktree.id)
    session.commit()
    return run_dict(run)


@router.post("/{project_id}/worktrees/{worktree_id}/keep", status_code=200)
def keep_project_worktree(project_id: UUID, worktree_id: UUID, body: WorktreeRequest, session: DB):
    project = get_project(session, project_id)
    if project.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Project settings changed. Reload before keeping a worktree.")
    worktree = session.get(Worktree, str(worktree_id))
    if worktree is None or worktree.project_id != project.id:
        raise HTTPException(404, "Worktree not found in this project")
    if worktree.removed_at is not None or not worktree.owned:
        raise HTTPException(409, "Only a prepared owned worktree can be kept")
    pin_expiry(worktree)
    session.commit()
    return worktree_dict(worktree)


@router.post("/{project_id}/worktrees/{worktree_id}/remove", status_code=202)
def remove_project_worktree(project_id: UUID, worktree_id: UUID, body: WorktreeRequest, session: DB):
    project = get_project(session, project_id)
    if project.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Project settings changed. Reload before removing a worktree.")
    worktree = session.get(Worktree, str(worktree_id))
    if worktree is None or worktree.project_id != project.id:
        raise HTTPException(404, "Worktree not found in this project")
    try:
        run = queue_worktree_removal(session, project, worktree, triggered_by="user")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return run_dict(run)
