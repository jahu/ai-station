"""Frozen project policies compose ordinary preparation/dependency/check Runs."""

import json
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.artifacts import register_file
from app.dependencies import depend_on
from app.events import append_event
from app.heartbeat import cancel_expired_coding
from app.models import Run
from app.permissions import require
from app.runner_client import RunnerClient
from app.runs import create_run, transition
from app.state import RunStatus
from app.task_control import stopped_task
from app.validation_environment import ValidationEnvironment


class ProjectCheckPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_install_dependencies: StrictBool = False
    auto_validate: StrictBool = False
    project_updated_at: str = ""
    validation_environment: ValidationEnvironment | None = None


def project_check_policy(project):
    if project is None:
        raise ValueError("The project policy is unavailable")
    return ProjectCheckPolicy(
        auto_install_dependencies=project.auto_install_dependencies,
        auto_validate=project.auto_validate,
        project_updated_at=project.updated_at.isoformat(),
        validation_environment=getattr(project, "validation_environment", None),
    ).model_dump(exclude_none=True)


class PlannedCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["test", "lint", "build"]
    argv: list[str] = Field(min_length=1, max_length=10)


PlanManifest = Annotated[
    dict[
        Literal[
            "requirements.txt", "pyproject.toml", "package.json", "requirements.lock", "requirements-dev.lock"
        ],
        Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None,
    ],
    Field(min_length=3, max_length=4),
]


class ProjectPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    worktree_run_id: UUID
    manifest_snapshot: PlanManifest
    node_manifest_snapshot: PlanManifest | None = None
    ecosystems: list[Literal["python", "node"]] = Field(max_length=2)
    commands: list[PlannedCommand] = Field(max_length=6)
    warnings: list[Annotated[str, Field(max_length=1000)]] = Field(max_length=4)


def checked_plan(payload, run):
    parsed = ProjectPlan.model_validate(payload)
    plan = parsed.model_dump(
        mode="json", exclude={"node_manifest_snapshot"} if parsed.node_manifest_snapshot is None else set()
    )
    if plan["project_id"] != run.project_id or plan["worktree_run_id"] != run.parameters["worktree_run_id"]:
        raise ValueError("Project preparation report belongs to another worktree")
    allowed = [(kind, ["npm", "run", kind]) for kind in ("test", "lint", "build")]
    policy = ProjectCheckPolicy.model_validate(run.parameters.get("project_check_policy") or {})
    environment = policy.validation_environment
    if environment and environment.node_directory not in {None, "."}:
        allowed.extend(
            (kind, ["npm", f"--prefix={environment.node_directory}", "run", kind])
            for kind in ("test", "lint", "build")
        )
    if environment and environment.node_directory and parsed.node_manifest_snapshot is None:
        raise ValueError("Component preparation requires the frozen Node manifest snapshot")
    for python in ("python3", ".venv/bin/python"):
        allowed.append(("test", [python, "-m", "pytest", "-q"]))
        for directory in (".", "tests"):
            allowed.append(("test", [python, "-m", "unittest", "discover", "-s", directory, "-v"]))
    if any((command["kind"], command["argv"]) not in allowed for command in plan["commands"]):
        raise ValueError("Project inspection returned an unsupported automatic check")
    if len(set(plan["ecosystems"])) != len(plan["ecosystems"]):
        raise ValueError("Duplicate project ecosystems")
    return plan


def queue_project_checks(session, source):
    policy = ProjectCheckPolicy.model_validate(source.parameters.get("project_check_policy") or {})
    if not (policy.auto_install_dependencies or policy.auto_validate):
        return False
    if source.metadata_json.get("project_plan_run_id"):
        return True
    run = create_run(
        session,
        source.task,
        run_type="inspection",
        capability="coding.plan_checks",
        executor_type="project_plan",
        execution_target="host",
        project_id=source.project_id,
        parent_run_id=source.id,
        permissions=["filesystem_read", "git_read"],
        retry_class="safe",
        parameters={
            "source_run_id": source.id,
            "worktree_id": source.parameters["worktree_id"],
            "worktree_run_id": source.parameters["worktree_run_id"],
            "project_check_policy": policy.model_dump(exclude_none=True),
            **(
                {"agent_coding_deadline": source.parameters["agent_coding_deadline"]}
                if source.parameters.get("agent_coding_deadline")
                else {}
            ),
        },
    )
    source.metadata_json = {
        **source.metadata_json,
        "project_plan_run_id": run.id,
        "validation_status": "preparing",
    }
    return True


class ProjectPlanExecutor:
    name = "project_plan"

    def execute(self, session, run):
        for permission in ("filesystem_read", "git_read"):
            require(run.effective_permissions, permission)
        session.refresh(run)
        if run.status == "cancel_requested" or stopped_task(session, run.task):
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(
            session,
            run,
            RunStatus.RUNNING,
            event_type="executor.started",
            payload={"operation": "inspect_project"},
        )
        policy = ProjectCheckPolicy.model_validate(run.parameters["project_check_policy"])
        payload = {
            "project_id": run.project_id,
            "worktree_run_id": run.parameters["worktree_run_id"],
            "install_dependencies": policy.auto_install_dependencies,
            "permissions": run.effective_permissions,
            **(
                {"validation_environment": policy.validation_environment.model_dump()}
                if policy.validation_environment
                else {}
            ),
        }
        session.commit()
        plan = checked_plan(RunnerClient().request("POST", "/v1/worktrees/plan", payload), run)
        session.refresh(run)
        cancel_expired_coding(session, run.id)
        if run.status == "cancel_requested" or stopped_task(session, run.task):
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        source = session.get(Run, run.parameters["source_run_id"])
        if (
            not source
            or source.metadata_json.get("project_plan_run_id") != run.id
            or source.status != "succeeded"
            or source.task_id != run.task_id
            or source.project_id != run.project_id
            or source.parameters["worktree_run_id"] != plan["worktree_run_id"]
            or source.parameters.get("project_check_policy") != policy.model_dump(exclude_none=True)
        ):
            raise ValueError("Project preparation lost its frozen coding source")
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(plan, handle)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="project-preparation.json",
                run_id=run.id,
                metadata={"project_id": run.project_id},
            )
        run.metadata_json = {**run.metadata_json, "project_plan": plan}
        append_event(session, run.id, "project.preparation.planned", plan)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        prerequisites = [run]
        common = {
            "worktree_id": source.parameters["worktree_id"],
            "worktree_run_id": plan["worktree_run_id"],
            "manifest_snapshot": plan["manifest_snapshot"],
            "project_check_policy": policy.model_dump(exclude_none=True),
            **(
                {"agent_coding_deadline": run.parameters["agent_coding_deadline"]}
                if run.parameters.get("agent_coding_deadline")
                else {}
            ),
        }
        if policy.auto_install_dependencies:
            for ecosystem in plan["ecosystems"]:
                child = create_run(
                    session,
                    run.task,
                    run_type="dependencies",
                    capability="coding.dependencies",
                    executor_type="project_dependencies",
                    execution_target="host",
                    project_id=run.project_id,
                    parent_run_id=source.id,
                    permissions=[
                        "filesystem_read",
                        "workspace_write",
                        "git_read",
                        "shell_project_commands",
                        "network_read",
                    ],
                    retry_class="inspect",
                    parameters={
                        **common,
                        "ecosystem": ecosystem,
                        **(
                            {
                                "directory": policy.validation_environment.node_directory or ".",
                                "manifest_snapshot": plan.get(
                                    "node_manifest_snapshot", plan["manifest_snapshot"]
                                ),
                            }
                            if ecosystem == "node" and policy.validation_environment
                            else {}
                        ),
                        **(
                            {"python_manifest": policy.validation_environment.python_manifest}
                            if ecosystem == "python"
                            and policy.validation_environment
                            and policy.validation_environment.python_manifest
                            else {}
                        ),
                    },
                )
                depend_on(session, child, prerequisites[-1])
                prerequisites.append(child)
        commands = source.parameters["commands"]
        if not commands and policy.auto_validate:
            commands = plan["commands"]
            source.metadata_json = {**source.metadata_json, "check_warnings": plan["warnings"]}
        source.metadata_json = {
            **source.metadata_json,
            "dependency_run_ids": [r.id for r in prerequisites[1:]],
            "automatic_commands": commands,
        }
        run.summary = (
            f"Project inspected; {len(prerequisites) - 1} dependency job(s), {len(commands)} check(s)."
        )
        from app.coding_tasks import queue_validation

        queue_validation(
            session,
            source,
            prepared=True,
            commands=commands,
            manifest_snapshot=plan["manifest_snapshot"],
            node_manifest_snapshot=plan.get("node_manifest_snapshot"),
            prerequisites=prerequisites,
        )
        return "done"


def freeze_environment_manifests(session, run):
    """Worker-only inspection; freeze once before dispatch, never in an HTTP handler."""
    environment = run.parameters.get("validation_environment")
    if not environment or "manifest_snapshot" in run.parameters:
        return True
    configured = ValidationEnvironment.model_validate(environment)
    session.commit()
    parsed = ProjectPlan.model_validate(
        RunnerClient().request(
            "POST",
            "/v1/worktrees/plan",
            {
                "project_id": run.project_id,
                "worktree_run_id": run.parameters["worktree_run_id"],
                "install_dependencies": False,
                "validation_environment": configured.model_dump(),
                "permissions": ["filesystem_read", "git_read"],
            },
        )
    )
    if (
        str(parsed.project_id) != run.project_id
        or str(parsed.worktree_run_id) != run.parameters["worktree_run_id"]
    ):
        raise ValueError("Project inspection belongs to another workspace")
    if configured.node_directory and parsed.node_manifest_snapshot is None:
        raise ValueError("Project inspection omitted component manifests")
    session.refresh(run)
    if run.status == "cancel_requested" or stopped_task(session, run.task):
        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        return False
    frozen = {"manifest_snapshot": parsed.manifest_snapshot}
    if parsed.node_manifest_snapshot is not None:
        frozen["node_manifest_snapshot"] = parsed.node_manifest_snapshot
    run.parameters = {**run.parameters, **frozen}
    append_event(session, run.id, "project.manifests.frozen", frozen)
    session.commit()
    return True
