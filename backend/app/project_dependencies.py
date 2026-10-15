"""Install declared Python dependencies into an owned worktree environment."""

import json
import tempfile
from pathlib import Path

from app.artifacts import register_file
from app.events import append_event
from app.native_job_executor import NativeJobExecutor
from app.runs import mark_failed, transition
from app.state import RunStatus


class ProjectDependenciesExecutor(NativeJobExecutor):
    name = "project_dependencies"
    permissions = (
        "filesystem_read",
        "workspace_write",
        "git_read",
        "shell_project_commands",
        "network_read",
    )
    error_type = "DependencyInstallFailed"

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "worktree_run_id": run.parameters["worktree_run_id"],
            "permissions": run.effective_permissions,
            **({"ecosystem": run.parameters["ecosystem"]} if "ecosystem" in run.parameters else {}),
            **(
                {"manifest_snapshot": run.parameters["manifest_snapshot"]}
                if "manifest_snapshot" in run.parameters
                else {}
            ),
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/dependencies", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/dependencies/{run_id}/report")

    def finish(self, session, run, report):
        if (
            report["run_id"] != run.id
            or report["project_id"] != run.project_id
            or report["worktree_run_id"] != run.parameters["worktree_run_id"]
        ):
            raise ValueError("Dependency report does not match its request")
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle, indent=2)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="dependencies.json",
                run_id=run.id,
                metadata={"project_id": run.project_id},
            )
        append_event(session, run.id, "dependencies.completed", report)
        run.metadata_json = {**run.metadata_json, "dependencies": report}
        node = report.get("ecosystem") == "node"
        installer = "npm ci" if node else "pip install"
        source = "npm registry" if node else "local vendor wheels" if report["source"] == "vendor" else "PyPI"
        if report.get("exit_code") != 0:
            run.summary = f"{installer} failed for {len(report['specifiers'])} requirement(s) from {report['manifest']}."
            mark_failed(
                session,
                run,
                "DependencyInstallFailed",
                f"{installer} failed; inspect the dependency report",
            )
            return "done"
        run.summary = (
            f"Installed {len(report['specifiers'])} requirement(s) from {report['manifest']} using {source}."
        )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        return "done"
