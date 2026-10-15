"""A connector snapshot is an ordinary cancellable owned Host Runner job."""

import json
import re
import tempfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from app.artifacts import register_file
from app.events import append_event
from app.models import Run
from app.native_job_executor import NativeJobExecutor
from app.runs import create_run, create_task, run_dict, transition
from app.state import RunStatus


def repository_name(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value)
        or value.split("/")[1] in {".", ".."}
        or value.endswith(".git")
    ):
        raise ValueError("Use a github.com owner/repository name, without a URL or .git")
    return value


def enqueue(session, row):
    from app.connectors import active_check
    from app.db import utcnow

    if not row.enabled:
        raise HTTPException(409, "Enable the connector before refreshing it")
    if active_check(session, row.id):
        raise HTTPException(409, "This connector already has an active refresh")
    repository = repository_name(row.config_json.get("repository"))
    task = create_task(
        session,
        title=f"Refresh {row.name}",
        prompt=f"Read GitHub overview for {repository}",
        capability="connector.github.read",
    )
    run = create_run(
        session,
        task,
        run_type="connector",
        capability="connector.github.read",
        executor_type="github_read",
        execution_target="host",
        parameters={"connector_id": row.id, "repository": repository, "operation": "overview"},
        permissions=["network_read", "github_read"],
        retry_class="inspect",
    )
    row.status, row.last_run_id, row.updated_at = "checking", run.id, utcnow()
    session.commit()
    return run_dict(run)


def saved_snapshot(session, row):
    # Keep the last successful observation visible during refresh or after failure.
    run = session.scalar(
        select(Run)
        .where(
            Run.executor_type == "github_read",
            Run.status == "succeeded",
            Run.parameters["connector_id"].as_string() == row.id,
            Run.parameters["repository"].as_string() == row.config_json.get("repository"),
        )
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(1)
    )
    return run.metadata_json.get("github_snapshot") if run else None


class GithubReadExecutor(NativeJobExecutor):
    name = "github_read"
    permissions = ("network_read", "github_read")
    error_type = "GithubReadFailed"

    def payload(self, run):
        return {
            "run_id": run.id,
            "repository": repository_name(run.parameters["repository"]),
            "operation": "overview",
            "permissions": list(run.effective_permissions),
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/github-read", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/github-read/{run_id}/report")

    def finish(self, session, run, report):
        if (
            report.get("run_id") != run.id
            or report.get("repository") != run.parameters["repository"]
            or len(json.dumps(report).encode()) > 256000
        ):
            raise ValueError("GitHub snapshot ownership or size mismatch")
        project = report.get("project")
        if (
            not isinstance(project, dict)
            or project.get("name", "").lower() != run.parameters["repository"].lower()
        ):
            raise ValueError("GitHub snapshot repository mismatch")
        base = "https://github.com/" + run.parameters["repository"]
        if project.get("url", "").lower() != base.lower():
            raise ValueError("Unexpected GitHub repository link")
        for key, section in (("issues", "issues"), ("pull_requests", "pull")):
            for item in report.get(key, []):
                if (
                    not isinstance(item, dict)
                    or type(item.get("number")) is not int
                    or item["number"] < 1
                    or not isinstance(item.get("title"), str)
                    or len(item["title"]) > 300
                    or not re.fullmatch(
                        re.escape(base) + f"/{section}/{item['number']}", item.get("url", ""), re.I
                    )
                ):
                    raise ValueError("Unexpected GitHub entry or link")
        for key in ("issues", "pull_requests"):
            if not isinstance(report.get(key), list) or len(report[key]) > 30:
                raise ValueError("GitHub snapshot list exceeds its limit")
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle)
            handle.flush()
            artifact = register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="github-overview.json",
                run_id=run.id,
                metadata={"connector_id": run.parameters["connector_id"], "operation": "github.read"},
            )
        result = {**report, "artifact_id": artifact.id}
        run.metadata_json = {**run.metadata_json, "github_snapshot": result}
        run.summary = f"Read {len(report['issues'])} open issues and {len(report['pull_requests'])} open pull requests from {run.parameters['repository']}."
        append_event(
            session,
            run.id,
            "connector.github.snapshot",
            {"artifact_id": artifact.id, "repository": run.parameters["repository"]},
        )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"
