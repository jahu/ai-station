"""Compose owned project setup with the existing coding workflow."""

import re

from fastapi import HTTPException
from pydantic import Field, StrictBool, StrictInt, ValidationError, model_validator

from app.project_setup import ProjectName


class ProjectBuildScope(ProjectName):
    executor: str = Field(default="local", pattern=r"^(local|cursor|codex)$")
    external_ai: StrictBool = False
    model: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._:/ -]*$")
    max_repair_attempts: StrictInt = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def permission_scope(self):
        if self.executor != "local" and not self.external_ai:
            raise ValueError("Allow sharing with the selected coding agent before creating the project")
        if self.executor == "local" and (self.external_ai or self.model):
            raise ValueError("Local coding uses the conversation's local model without external consent")
        if self.executor != "local" and self.max_repair_attempts:
            raise ValueError("Automatic repair is available only for local coding")
        return self


def project_build_request(params):
    action = params["action"]
    if action not in {"auto", "project.create_code"}:
        return None
    scope = params.get("new_project")
    prompt = params["content"].strip()
    if not scope:
        if action != "auto" or any(
            params.get(key) for key in ("coding", "commit", "publish", "load", "stop")
        ):
            return None
        match = re.fullmatch(
            r"(?:create|make|stw[oó]rz|utw[oó]rz)\s+(?:(?:a|new|nowy)\s+){0,2}"
            r"(?:project|projekt)\s+(?:(?:named|called|o nazwie|nazwany)\s+)?"
            r"(\"[^\"]{1,200}\"|'[^']{1,200}'|“[^”]{1,200}”|[^\"'“”\r\n]{1,200}?)"
            r"\s+(?:and(?:\s+then)?|then|i(?:\s+potem)?|potem|następnie)\s+"
            r"((?:build|create|write|implement|zbuduj|stw[oó]rz|napisz|zaimplementuj)\s+.+)",
            prompt,
            re.I | re.S,
        )
        if not match:
            return None
        name, prompt = match.groups()
        name = name.strip()
        if len(name) >= 2 and (name[0], name[-1]) in {('"', '"'), ("'", "'"), ("“", "”")}:
            name = name[1:-1].strip()
        if re.search(r"\b(?:with|using|używając|za pomocą)\s+(?:cursor|codex)\b", prompt, re.I):
            raise HTTPException(
                422, "Choose Create project & build and explicitly allow sharing with Cursor/Codex"
            )
        scope = {"name": name}
    try:
        scope = ProjectBuildScope.model_validate(scope)
    except ValidationError as exc:
        raise HTTPException(422, "Choose a readable project name and an authorized coding agent") from exc
    if not prompt or len(prompt) > 10000:
        raise HTTPException(422, "Describe the coding goal in at most 10,000 characters")
    return scope, prompt


def queue_project_build(session, setup, project):
    """Called in the confirmed project registration/completion transaction."""
    from app.codex_coding import CodexTask
    from app.coding_tasks import enqueue_coding_task
    from app.cursor_coding import CursorTask
    from app.local_coding import LocalCodingTask
    from app.providers import ProviderError
    from app.runs import create_run, mark_failed, transition
    from app.state import RunStatus

    request = setup.parameters.get("coding_request")
    if not request:
        return
    scope = ProjectBuildScope.model_validate(request["scope"])
    fields = {
        "project_id": project.id,
        "expected_updated_at": project.updated_at,
        "prompt": request["prompt"],
        "files": [],
        "explore": True,
    }
    try:
        if scope.executor == "local":
            body = LocalCodingTask(
                **fields, model=request["model"], max_repair_attempts=scope.max_repair_attempts
            )
        else:
            body = (CodexTask if scope.executor == "codex" else CursorTask)(
                **fields,
                model=scope.model,
                external_ai=scope.external_ai,
            )
        child = enqueue_coding_task(
            session, body, provider=scope.executor, task=setup.task, parent_run_id=setup.id
        )
    except (HTTPException, ProviderError, ValidationError) as exc:
        # The project exists; preserve it and make the failed next stage explicit.
        child = create_run(
            session,
            setup.task,
            run_type="worktree",
            capability="coding.prepare",
            executor_type="worktree_prepare",
            project_id=project.id,
            parent_run_id=setup.id,
            parameters={"coding_request": request},
            metadata={
                "execution_location": "local" if scope.executor == "local" else "external",
                "next_executor": "local_proposal"
                if scope.executor == "local"
                else scope.executor + "_proposal",
            },
        )
        child.worker_id = setup.worker_id
        transition(
            session,
            child,
            RunStatus.CLAIMED,
            event_type="run.claimed",
            payload={"worker_id": setup.worker_id, "preflight_only": True},
        )
        mark_failed(
            session,
            child,
            "CodingSetupFailed",
            str(exc.detail) if isinstance(exc, HTTPException) else str(exc),
        )
    setup.metadata_json = {**setup.metadata_json, "coding_run_id": child.id}
    setup.summary = "Project created; coding preparation " + (
        "failed." if child.status == "failed" else "queued."
    )
