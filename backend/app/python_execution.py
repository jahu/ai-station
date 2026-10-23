"""Owned Python execution Runs; agent workflow publication uses this service."""

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from app.artifacts import register_file
from app.config import get_settings
from app.events import append_event
from app.models import Artifact, Worktree
from app.native_job_executor import NativeJobExecutor
from app.paths import artifact_relative
from app.permissions import require
from app.runs import create_run, mark_failed, transition
from app.state import RunStatus
from app.validation_environment import relative_directory
from app.worktree_expiry import refresh_expiry

PERMISSIONS = ("filesystem_read", "workspace_write", "python_execute")
MAX_INPUT = 16 * 1024 * 1024
MAX_INPUT_TOTAL = 32 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024


class PythonParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worktree_id: UUID
    script_relative: str = Field(min_length=1, max_length=200)
    script_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    script_artifact_id: UUID | None = None
    input_artifact_ids: list[UUID] = Field(default_factory=list, max_length=8)
    expected_outputs: list[str] = Field(min_length=1, max_length=8)
    optional_outputs: list[str] = Field(default_factory=list, max_length=8)
    maximum_runtime: int = Field(default=120, ge=1, le=600, strict=True)

    @field_validator("script_relative")
    @classmethod
    def script(cls, value):
        relative_directory(value)
        if not value.endswith(".py"):
            raise ValueError("Choose a Python source entrypoint")
        return value

    @field_validator("expected_outputs", "optional_outputs")
    @classmethod
    def outputs(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Output filenames must be unique")
        for value in values:
            relative_directory(value)
            if len(value) > 200 or value == ".":
                raise ValueError("Choose bounded output filenames")
        return values

    @model_validator(mode="after")
    def inputs(self):
        names = self.expected_outputs + self.optional_outputs
        if len(names) > 8 or len(names) != len(set(names)):
            raise ValueError("Required and optional outputs must be disjoint and total at most eight")
        if len(set(self.input_artifact_ids)) != len(self.input_artifact_ids):
            raise ValueError("Input artifacts must be unique")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_identity(self, handler):
        value = handler(self)
        if not self.optional_outputs:
            value.pop("optional_outputs", None)
        return value


def output_names_match(required, optional, actual):
    """Validate the native report independently of the execution boundary."""
    if not all(isinstance(names, list) for names in (required, optional, actual)):
        return False
    approved = required + optional
    if not required or len(approved) > 8 or not all(isinstance(name, str) for name in approved + actual):
        return False
    if len(approved) != len(set(approved)):
        return False
    if actual[: len(required)] != required or len(actual) < len(required):
        return False
    cursor = -1
    for name in actual[len(required) :]:
        if name not in optional:
            return False
        index = optional.index(name)
        if index <= cursor:
            return False
        cursor = index
    return True


def input_snapshots(session, ids):
    result = []
    for aid in ids:
        artifact = session.get(Artifact, str(aid))
        if artifact is None or artifact.trashed_at is not None:
            raise ValueError("A selected Python input is unavailable")
        suffix = Path(artifact.relative_path).suffix.lower()
        if (
            suffix not in {".xlsx", ".csv", ".json", ".txt"}
            or artifact.relative_path != artifact_relative(artifact.id, suffix)
            or not artifact.sha256
            or not 0 <= artifact.size_bytes <= MAX_INPUT
        ):
            raise ValueError("Select bounded stored CSV, XLSX, JSON or text inputs")
        result.append(
            {
                "artifact_id": artifact.id,
                "suffix": suffix,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            }
        )
    if sum(item["size_bytes"] for item in result) > MAX_INPUT_TOTAL:
        raise ValueError("Python input files exceed their total limit")
    return result


def enqueue_python(session, task, parameters, *, permissions, parent_run_id=None):
    for permission in PERMISSIONS:
        require(permissions, permission)
    body = PythonParameters.model_validate(parameters)
    tree = session.get(Worktree, str(body.worktree_id))
    if tree is None or not tree.owned or tree.removed_at is not None or tree.project_id != task.project_id:
        raise ValueError("Python execution requires this Task’s owned project worktree")
    inputs = input_snapshots(session, body.input_artifact_ids)
    run = create_run(
        session,
        task,
        run_type="python",
        capability="agent.python",
        executor_type="python",
        execution_target="container",
        permissions=list(PERMISSIONS),
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={**body.model_dump(mode="json"), "worktree_run_id": tree.run_id, "inputs": inputs},
    )
    refresh_expiry(session, worktree_id=tree.id)
    return run


def read_owned_file(relative, size, digest, *, limit=MAX_FILE):
    path = get_settings().data_dir.resolve() / relative
    if path.resolve() != path or type(size) is not int or not 0 <= size <= limit:
        raise ValueError("Redirected or oversized Python result")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != size:
            raise ValueError("Python result must be the recorded regular file")
        data = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Python result changed before artifact adoption")
    return path


class PythonExecutor(NativeJobExecutor):
    name = "python"
    permissions = PERMISSIONS
    error_type = "PythonExecutionFailed"

    def execute(self, session, run):
        if "agent_data" in run.parameters and run.status not in {"cancel_requested", "canceled"}:
            from app.data_agents import validate_python_dispatch

            validate_python_dispatch(session, run)
        return super().execute(session, run)

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            **{
                key: run.parameters[key]
                for key in (
                    "worktree_run_id",
                    "script_relative",
                    "script_sha256",
                    "inputs",
                    "expected_outputs",
                    "maximum_runtime",
                )
            },
            **(
                {"script_artifact_id": run.parameters["script_artifact_id"]}
                if run.parameters.get("script_artifact_id")
                else {}
            ),
            "permissions": run.effective_permissions,
            **(
                {"optional_outputs": run.parameters["optional_outputs"]}
                if run.parameters.get("optional_outputs")
                else {}
            ),
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/python", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/python/{run_id}/report")

    def finish(self, session, run, report):
        if (
            report.get("run_id") != run.id
            or report.get("project_id") != run.project_id
            or report.get("worktree_run_id") != run.parameters["worktree_run_id"]
            or report.get("script_sha256") != run.parameters["script_sha256"]
            or type(report.get("exit_code")) is not int
            or type(report.get("succeeded")) is not bool
        ):
            raise ValueError("Python report does not match its frozen request")
        outputs = report.get("outputs")
        if not isinstance(outputs, list) or len(outputs) > 8:
            raise ValueError("Invalid Python output list")
        success = report["exit_code"] == 0 and report.get("error") is None
        if (
            success != report["succeeded"]
            or (not success and outputs)
            or success
            and not output_names_match(
                run.parameters["expected_outputs"],
                run.parameters.get("optional_outputs", []),
                [item.get("name") for item in outputs],
            )
        ):
            raise ValueError("Python report contradicts required outputs")
        paths = []
        total = 0
        for index, item in enumerate(outputs):
            suffix = Path(item["name"]).suffix.lower()
            if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
                suffix = ".bin"
            expected = f"runtime/python/{run.id}/output-{index}{suffix}"
            if (
                set(item) != {"name", "relative_path", "size_bytes", "sha256"}
                or item["relative_path"] != expected
            ):
                raise ValueError("Unexpected Python output path")
            paths.append(read_owned_file(expected, item["size_bytes"], item["sha256"]))
            total += item["size_bytes"]
        if total > 16 * 1024 * 1024:
            raise ValueError("Python results exceed the total size limit")
        # Adoption occurs only after every export passed ownership/hash checks.
        input_ids = [item["artifact_id"] for item in run.parameters["inputs"]]
        script_relative = f"runtime/python/{run.id}/inputs/script.py"
        script_size = (get_settings().data_dir / script_relative).stat().st_size
        script_source = read_owned_file(
            script_relative, script_size, run.parameters["script_sha256"], limit=128 * 1024
        )
        script_artifact = register_file(
            session,
            source=script_source,
            artifact_type="text",
            mime_type="text/x-python",
            original_filename=Path(run.parameters["script_relative"]).name,
            run_id=run.id,
            artifact_id=str(uuid5(NAMESPACE_URL, f"python:{run.id}:script")),
            metadata={"python_source": True},
            parent_artifact_ids=input_ids,
        )
        lineage = [script_artifact.id, *input_ids]
        registered = []
        for index, (item, source) in enumerate(zip(outputs, paths, strict=True)):
            internal = "agent_data" in run.parameters and index >= 2
            suffix = source.suffix.lower()
            kind, mime = {
                ".csv": ("document", "text/csv"),
                ".json": ("json", "application/json"),
                ".txt": ("text", "text/plain"),
                ".md": ("markdown", "text/markdown"),
                ".xlsx": ("document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            }.get(suffix, ("document", "application/octet-stream"))
            artifact = register_file(
                session,
                source=source,
                artifact_type=kind,
                mime_type="application/octet-stream" if internal else mime,
                original_filename=Path(item["name"]).name,
                run_id=run.id,
                artifact_id=str(uuid5(NAMESPACE_URL, f"python:{run.id}:output:{index}")),
                metadata={
                    "python_execution": True,
                    "output_name": item["name"],
                    "script_sha256": run.parameters["script_sha256"],
                    **({"internal_data_output": True} if internal else {}),
                },
                parent_artifact_ids=lineage,
            )
            registered.append(artifact.id)
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="python-execution.json",
                run_id=run.id,
                parent_artifact_ids=lineage,
                metadata={"python_execution_report": True},
            )
        run.metadata_json = {
            **run.metadata_json,
            "python_execution": report,
            "output_artifact_ids": registered,
            "script_artifact_id": script_artifact.id,
        }
        append_event(
            session,
            run.id,
            "python.completed",
            {"exit_code": report["exit_code"], "output_artifact_ids": registered},
        )
        if success:
            run.summary = f"Python completed; {len(registered)} verified output file(s)."
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        else:
            mark_failed(
                session,
                run,
                "PythonProgramFailed",
                report.get("error") or f"Python exited with code {report['exit_code']}",
            )
        if "agent_data" in run.parameters:
            from app.data_agents import queue_result

            queue_result(session, run)
        return "done"
