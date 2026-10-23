"""Durable project creation, completed by the native Runner."""

import json
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope
from app.models import Project
from app.native_job_executor import NativeJobExecutor
from app.projects import ProjectSettings
from app.runs import create_run, create_task, run_dict, transition
from app.state import RunStatus

router = APIRouter(prefix="/api/projects")


class ProjectAutomation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_install_dependencies: StrictBool = False
    auto_validate: StrictBool = False


class ProjectName(ProjectAutomation):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def readable(cls, value):
        return ProjectSettings.name_not_blank(value)


@router.post("/create", status_code=202)
def create_project(body: ProjectName, session: Annotated[Session, Depends(session_scope)]):
    run = enqueue_project(session, body)
    session.commit()
    return run_dict(run)


def enqueue_project(session, body: ProjectName, *, task=None, parent_run_id=None):
    task = task or create_task(
        session,
        title=f"Create {body.name}",
        prompt="Create an application-owned project",
        capability="project.create",
    )
    run = create_run(
        session,
        task,
        run_type="project",
        capability="project.create",
        executor_type="project_setup",
        execution_target="host",
        permissions=["workspace_write", "git_write"],
        retry_class="inspect",
        parameters={
            "project_id": str(uuid4()),
            "settings": ProjectSettings(
                name=body.name,
                preferred_executor="local",
                auto_install_dependencies=body.auto_install_dependencies,
                auto_validate=body.auto_validate,
            ).model_dump(),
        },
        parent_run_id=parent_run_id,
    )
    return run


class ProjectSetupExecutor(NativeJobExecutor):
    permissions = ("workspace_write", "git_write")
    error_type = "ProjectSetupFailed"

    def execute(self, session, run):
        if "agent_workspace" in run.parameters and run.status not in {"cancel_requested", "canceled"}:
            from app.agent_workspace import coding_deadline, reviewed_workspace

            parent, definition, _ = reviewed_workspace(session, run)
            coding_deadline(parent, definition)
        if "conversation_data_workspace" in run.parameters and run.status not in {
            "cancel_requested",
            "canceled",
        }:
            from app.conversation_data import reviewed_workspace

            reviewed_workspace(session, run)
        return super().execute(session, run)

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.parameters["project_id"],
            "name": run.parameters["settings"]["name"],
            "permissions": run.effective_permissions,
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/projects/create", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/projects/created/{run_id}")

    def finish(self, session, run, report):
        with session.begin_nested():
            return self._finish(session, run, report)

    def _finish(self, session, run, report):
        workspace = None
        if "agent_workspace" in run.parameters:
            from app.agent_workspace import reviewed_workspace

            workspace = reviewed_workspace(session, run)
        if report["run_id"] != run.id or report["project_id"] != run.parameters["project_id"]:
            raise ValueError("Project creation ownership mismatch")
        settings = {**run.parameters["settings"], "default_branch": "main", "integration_branch": "develop"}
        project = Project(id=report["project_id"], repo_path=report["repo_path"], **settings)
        session.add(project)
        session.flush()
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="project-setup.json",
                run_id=run.id,
                metadata={"project_id": project.id},
            )
        if "conversation_data_workspace" in run.parameters:
            from app.conversation_data import finish_workspace, reviewed_workspace

            data_context = reviewed_workspace(session, run)
            run.metadata_json = {**run.metadata_json, "project": report}
            return finish_workspace(session, run, project, data_context)
        if workspace is not None:
            from app.agent_workspace import finish_workspace

            run.metadata_json = {**run.metadata_json, "project": report}
            return finish_workspace(session, run, project, workspace)
        run.project_id = run.task.project_id = project.id
        run.metadata_json = {**run.metadata_json, "project": report}
        run.summary = "Project created with Git and a Python environment. Ready for coding."
        transition(
            session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={"project_id": project.id}
        )
        from app.project_build import queue_project_build

        queue_project_build(session, run, project)
        return "done"
