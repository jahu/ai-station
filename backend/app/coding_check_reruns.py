"""An explicit same-task check repeat, without inference or dependency setup."""

from pathlib import PurePosixPath
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update

from app.db import utcnow
from app.events import append_event
from app.models import Project, Run, Worktree
from app.project_activity import project_write_condition
from app.project_checks import PlanManifest
from app.runs import create_run
from app.state import TERMINAL
from app.task_control import lock_task
from app.validation_environment import ValidationEnvironment
from app.worktree_expiry import refresh_expiry

PERMISSIONS = ["filesystem_read", "workspace_write", "git_read", "shell_project_commands"]


class RecordedCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["test", "lint", "build"]
    argv: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def checked_arguments(self):
        if (
            not self.argv[0].strip()
            or self.argv[0].startswith("-")
            or PurePosixPath(self.argv[0]).name in {"sh", "bash", "dash", "zsh", "fish", "sudo", "su"}
            or any(ord(c) < 32 for arg in self.argv for c in arg)
        ):
            raise ValueError("Recorded checks require bounded project executables")
        return self


class RecordedChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commands: list[RecordedCommand] = Field(min_length=1, max_length=60)
    manifest_snapshot: PlanManifest | None = None
    node_manifest_snapshot: PlanManifest | None = None
    validation_environment: ValidationEnvironment | None = None
    output_contract: Literal["static_site"] | None = None

    @model_validator(mode="after")
    def bounded(self):
        if sum(len(arg) for command in self.commands for arg in command.argv) > 32000:
            raise ValueError("Recorded checks exceed the command limit")
        return self


def enqueue_check_rerun(session, source_id, expected_validation_id):
    from app.coding_sessions import PROPOSALS

    # First DB statement: serialize stale/double requests before reading state.
    accepted = session.execute(
        update(Run)
        .where(
            Run.id == source_id,
            Run.status == "succeeded",
            Run.executor_type.in_(PROPOSALS),
            Run.metadata_json["validation_run_id"].as_string() == expected_validation_id,
        )
        .values(summary=Run.summary),
        execution_options={"synchronize_session": False},
    )
    if accepted.rowcount != 1:
        raise HTTPException(409, "The coding turn or its checks changed. Reload before repeating checks.")
    source = session.get(Run, source_id)
    session.refresh(source)
    # Serialize different turns for the same project as well (including future
    # row-locking database implementations), before the active-project guard.
    session.execute(update(Project).where(Project.id == source.project_id).values(name=Project.name))
    project = session.get(Project, source.project_id)
    task = source.task
    lock_task(session, task)
    previous = session.get(Run, expected_validation_id)
    latest = session.scalar(
        select(Run.id)
        .where(Run.task_id == task.id, Run.executor_type.in_(PROPOSALS))
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(1)
    )
    tree = session.get(Worktree, source.parameters.get("worktree_id", ""))
    if (
        project is None
        or task.project_id != source.project_id
        or latest != source.id
        or source.metadata_json.get("continuation_run_id")
        or source.metadata_json.get("repair_run_id")
        or previous is None
        or previous.executor_type != "project_validation"
        or previous.run_type != "validation"
        or previous.capability != "coding.validate"
        or previous.execution_target != "host"
        or previous.parent_run_id != source.id
        or previous.task_id != task.id
        or previous.project_id != source.project_id
        or previous.status not in TERMINAL
        or set(previous.effective_permissions) != set(PERMISSIONS)
        or tree is None
        or not tree.owned
        or tree.removed_at is not None
        or tree.project_id != source.project_id
        or tree.run_id != source.parameters.get("worktree_run_id")
        or previous.parameters.get("worktree_id") != tree.id
        or previous.parameters.get("worktree_run_id") != tree.run_id
    ):
        raise HTTPException(409, "The completed coding turn and its owned check workspace are required")
    undispatched = (
        previous.status in {"failed", "canceled"}
        and not previous.metadata_json.get("dispatch_attempted")
        and previous.pid is None
        and previous.process_group_id is None
        and previous.runner_id is None
        and previous.started_at is None
    )
    if previous.metadata_json.get("process_confirmed_gone") is not True and not undispatched:
        raise HTTPException(409, "Inspect or stop the previous check process before repeating checks")
    if session.scalar(
        select(Run.id)
        .where(Run.project_id == project.id, Run.status.not_in(TERMINAL), project_write_condition())
        .limit(1)
    ):
        raise HTTPException(409, "Wait for this project's active work to finish")
    preparation = session.get(Run, tree.run_id)
    if preparation is None or preparation.status != "succeeded" or preparation.project_id != project.id:
        raise HTTPException(409, "Workspace preparation must still be valid")
    try:
        from app.coding_output import validation_contract

        validation_contract(session, previous)
        snapshot = RecordedChecks.model_validate(
            {
                "commands": previous.parameters.get("commands"),
                **{
                    key: previous.parameters.get(key)
                    for key in (
                        "manifest_snapshot",
                        "node_manifest_snapshot",
                        "validation_environment",
                        "output_contract",
                    )
                },
            }
        ).model_dump(mode="json", exclude_none=True)
    except ValueError as exc:
        raise HTTPException(409, "Recorded checks are invalid; inspect the previous Run") from exc
    task.metadata_json = {
        key: value for key, value in task.metadata_json.items() if key != "stop_requested_at"
    }
    task.updated_at = utcnow()
    run = create_run(
        session,
        task,
        run_type="validation",
        capability="coding.validate",
        executor_type="project_validation",
        execution_target="host",
        project_id=project.id,
        parent_run_id=source.id,
        permissions=PERMISSIONS,
        retry_class="inspect",
        triggered_by="user",
        parameters={
            "worktree_id": tree.id,
            "worktree_run_id": tree.run_id,
            **snapshot,
            "rerun_of": previous.id,
            "manual_checks_only": True,
        },
        metadata={"requested_action": "repeat_recorded_checks", "source_run_id": source.id},
    )
    source.metadata_json = {
        **source.metadata_json,
        "validation_run_id": run.id,
        "validation_status": "queued",
    }
    refresh_expiry(session, worktree_id=tree.id)
    append_event(
        session,
        run.id,
        "validation.rerun_requested",
        {
            "source_run_id": source.id,
            "previous_validation_run_id": previous.id,
            "model_inference": False,
            "dependency_installation": False,
        },
    )
    return run
