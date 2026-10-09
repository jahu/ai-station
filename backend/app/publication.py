"""Explicitly approved GitHub publication of a reviewed native commit."""

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.events import append_event
from app.gitpolicy import GitPolicyError, assert_branch_allowed, normalize_policy
from app.models import Approval, Project, Run
from app.native_job_executor import NativeJobExecutor
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, run_dict, transition
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/coding")
DB = Annotated[Session, Depends(session_scope)]


def source_commit(session, source_id):
    source = session.get(Run, str(source_id))
    if source is None:
        raise HTTPException(404, "Commit Run not found")
    if (
        source.executor_type != "reviewed_commit"
        or source.status != "succeeded"
        or not source.metadata_json.get("git_commit")
    ):
        raise HTTPException(409, "A successful reviewed commit is required")
    return source


@router.get("/runs/{source_id}/publication")
def preview(source_id: UUID, session: DB):
    source = source_commit(session, source_id)
    project = session.get(Project, source.project_id)
    if project is None:
        raise HTTPException(409, "Project is unavailable")
    version = project.updated_at
    session.commit()
    try:
        target = RunnerClient().request("GET", f"/v1/runs/reviewed-commit/{source_id}/publication")
    except (RunnerError, RunnerUnavailable) as exc:
        raise HTTPException(409, str(exc)) from exc
    session.refresh(project)
    session.refresh(source)
    if project.updated_at != version:
        raise HTTPException(409, "Project changed; reload publication details")
    policy = normalize_policy(project.pr_policy)
    blocked = None
    if not policy["push_task_branch"] or not policy["pr_to_integration"]:
        blocked = "Enable task-branch push and integration PRs in this project's policy first."
    if project.integration_branch in {*project.protected_branches, project.default_branch, "main", "master"}:
        blocked = "Choose a non-production integration branch in project settings."
    return {
        **target,
        "base": project.integration_branch,
        "expected_updated_at": version,
        "project_id": project.id,
        "blocked_reason": blocked,
        "publication_run_id": source.metadata_json.get("publication_run_id"),
    }


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    approved: Literal[True]
    repository: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$", max_length=140)
    commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    base: str = Field(min_length=1, max_length=200)
    expected_updated_at: datetime
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20000)


def enqueue_publication(session, source, body: PublishBody):
    project = session.get(Project, source.project_id)
    if project is None or project.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Project changed; reload publication details")
    if source.metadata_json.get("publication_run_id"):
        raise HTTPException(409, "Publication was already requested; inspect that Run and GitHub")
    policy = normalize_policy(project.pr_policy)
    if not policy["push_task_branch"] or not policy["pr_to_integration"]:
        raise HTTPException(403, "Project policy does not allow task-branch publication and integration PRs")
    protected = sorted({*project.protected_branches, project.default_branch, "main", "master"})
    commit = source.metadata_json["git_commit"]
    if body.base != project.integration_branch or body.base in protected or body.commit != commit["commit"]:
        raise HTTPException(
            409, "Publication must match the reviewed commit and non-production integration branch"
        )
    try:
        assert_branch_allowed(commit["branch"], protected, action="publish")
    except GitPolicyError as exc:
        raise HTTPException(403, str(exc)) from exc
    if session.scalar(
        select(Run.id).where(Run.project_id == project.id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "This project has an active Run")
    params = {
        "source_run_id": source.id,
        "worktree_run_id": commit["worktree_run_id"],
        "repository": body.repository,
        "commit": body.commit,
        "base": body.base,
        "branch": commit["branch"],
        "protected_branches": protected,
        "title": body.title,
        "body": body.body,
        "approved": True,
    }
    run = create_run(
        session,
        source.task,
        run_type="git",
        capability="coding.publish",
        executor_type="github_publication",
        execution_target="host",
        project_id=project.id,
        parent_run_id=source.id,
        permissions=list(GithubPublicationExecutor.permissions),
        retry_class="inspect",
        parameters=params,
    )
    approval = Approval(
        run_id=run.id,
        action="github.publish",
        risk="high",
        reason="User confirmed this commit, GitHub repository and draft integration PR",
        payload=params,
        resolution="granted",
        resolved_at=utcnow(),
    )
    session.add(approval)
    session.flush()
    run.parameters = {**params, "approval_id": approval.id}
    run.metadata_json = {"execution_location": "external", "approval_id": approval.id}
    source.metadata_json = {**source.metadata_json, "publication_run_id": run.id}
    append_event(
        session, run.id, "approval.requested", {"approval_id": approval.id, "action": approval.action}
    )
    append_event(session, run.id, "approval.granted", {"approval_id": approval.id, "by": "user"})
    return run


@router.post("/runs/{source_id}/publication", status_code=202)
def publish(source_id: UUID, body: PublishBody, session: DB):
    run = enqueue_publication(session, source_commit(session, source_id), body)
    session.commit()
    return run_dict(run)


@router.post("/runs/{publication_id}/reconcile", status_code=202)
def reconcile_publication(publication_id: UUID, session: DB):
    source = session.get(Run, str(publication_id))
    if source is None or source.executor_type != "github_publication":
        raise HTTPException(404, "Publication Run not found")
    if source.status not in {"failed", "interrupted", "canceled"}:
        raise HTTPException(409, "Reconcile only inspects a stopped publication Run")
    if source.metadata_json.get("publication", {}).get("pr_url"):
        raise HTTPException(409, "This publication already recorded a pull request")
    previous = session.get(Run, source.metadata_json.get("reconcile_run_id", ""))
    if previous is not None and previous.status not in TERMINAL:
        raise HTTPException(409, "Reconciliation is already running")
    if previous is not None and previous.status == "succeeded":
        raise HTTPException(409, "Reconciliation already recorded GitHub's state; inspect that Run")
    if not source.metadata_json.get("dispatch_attempted"):
        raise HTTPException(409, "Publication never reached GitHub")
    if session.scalar(
        select(Run.id).where(Run.project_id == source.project_id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "This project has an active Run")
    run = create_run(
        session,
        source.task,
        run_type="git",
        capability="coding.publish.reconcile",
        executor_type="publication_reconcile",
        execution_target="host",
        project_id=source.project_id,
        parent_run_id=source.id,
        permissions=list(PublicationReconcileExecutor.permissions),
        retry_class="inspect",
        parameters={
            "publication_run_id": source.id,
            "source_run_id": source.parameters["source_run_id"],
            "repository": source.parameters["repository"],
            "commit": source.parameters["commit"],
            "base": source.parameters["base"],
            "branch": source.parameters["branch"],
        },
    )
    source.metadata_json = {**source.metadata_json, "reconcile_run_id": run.id}
    session.commit()
    return run_dict(run)


class GithubPublicationExecutor(NativeJobExecutor):
    name = "github_publication"
    permissions = ("filesystem_read", "git_read", "git_write", "network_external")
    error_type = "PublicationFailed"

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "permissions": run.effective_permissions,
            **{
                key: run.parameters[key]
                for key in (
                    "source_run_id",
                    "approval_id",
                    "approved",
                    "repository",
                    "commit",
                    "base",
                    "protected_branches",
                    "title",
                    "body",
                )
            },
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/github-publication", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/github-publication/{run_id}/report")

    def execute(self, session, run):
        approval = session.get(Approval, run.parameters["approval_id"])
        if (
            approval is None
            or approval.run_id != run.id
            or approval.resolution != "granted"
            or approval.action != "github.publish"
            or any(run.parameters.get(k) != v for k, v in approval.payload.items())
        ):
            raise ValueError("Publication approval is missing or no longer matches its scope")
        result = super().execute(session, run)
        if run.status in {"failed", "canceled", "interrupted"} and run.metadata_json.get(
            "dispatch_attempted"
        ):
            session.commit()
            try:
                progress = RunnerClient().request("GET", f"/v1/runs/github-publication/{run.id}/progress")
            except (RunnerError, RunnerUnavailable):
                progress = {"stage": "unknown", "inspection_required": True}
            run.metadata_json = {**run.metadata_json, "publication_progress": progress}
        return result

    def finish(self, session, run, report):
        if (
            report["run_id"] != run.id
            or report["source_run_id"] != run.parameters["source_run_id"]
            or report["project_id"] != run.project_id
            or report["worktree_run_id"] != run.parameters["worktree_run_id"]
            or any(report[key] != run.parameters[key] for key in ("repository", "commit", "base", "branch"))
            or report["stage"] != "succeeded"
            or not re.fullmatch(
                r"https://github\.com/" + re.escape(run.parameters["repository"]) + r"/pull/[1-9][0-9]*",
                report["pr_url"],
            )
        ):
            raise ValueError("Publication report differs from the approved request")
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="github-publication.json",
                run_id=run.id,
                metadata={"project_id": run.project_id, "commit": report["commit"]},
            )
        run.metadata_json = {**run.metadata_json, "publication": report}
        run.summary = f"Published {report['branch']} and opened a draft PR to {report['base']}"
        append_event(
            session,
            run.id,
            "git.branch.published",
            {"repository": report["repository"], "branch": report["branch"], "commit": report["commit"]},
        )
        append_event(
            session,
            run.id,
            "git.pull_request.created",
            {"url": report["pr_url"], "draft": True, "base": report["base"]},
        )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


class PublicationReconcileExecutor(NativeJobExecutor):
    name = "publication_reconcile"
    permissions = ("filesystem_read", "git_read", "network_external")
    error_type = "PublicationReconcileFailed"

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "permissions": run.effective_permissions,
            "publication_run_id": run.parameters["publication_run_id"],
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/publication-reconcile", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/publication-reconcile/{run_id}/report")

    def finish(self, session, run, report):
        source = session.get(Run, run.parameters["publication_run_id"])
        if (
            source is None
            or source.executor_type != "github_publication"
            or report["run_id"] != run.id
            or report["publication_run_id"] != source.id
            or report["project_id"] != run.project_id
            or any(report[key] != run.parameters[key] for key in ("repository", "commit", "base", "branch"))
            or report["outcome"]
            not in {"not_on_github", "recorded_existing_pr", "created_draft_pr", "recorded_local_report"}
        ):
            raise ValueError("Publication reconcile report does not match the queued request")
        if report["pr_url"] and not re.fullmatch(
            r"https://github\.com/" + re.escape(run.parameters["repository"]) + r"/pull/[1-9][0-9]*",
            report["pr_url"],
        ):
            raise ValueError("Reconcile reported an unexpected PR URL")
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="github-publication-reconcile.json",
                run_id=run.id,
                metadata={"project_id": run.project_id, "outcome": report["outcome"]},
            )
        run.metadata_json = {**run.metadata_json, "publication": report}
        if report["pr_url"]:
            source.metadata_json = {**source.metadata_json, "publication": report}
            run.summary = f"Recorded draft PR {report['pr_url']} without pushing again"
            event = (
                "git.pull_request.created"
                if report["outcome"] == "created_draft_pr"
                else "git.pull_request.recorded"
            )
            append_event(
                session, run.id, event, {"url": report["pr_url"], "draft": True, "base": report["base"]}
            )
        else:
            run.summary = "GitHub does not have this task branch. Publication was not retried."
        append_event(session, run.id, "git.publication.reconciled", report)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"
