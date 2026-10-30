"""Operator access operations enqueue durable Runs; workers alone change services."""

import secrets
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.db import session_scope
from app.events import append_event
from app.models import Run, Setting
from app.permissions import require
from app.private_ui_state import lock, operation_facts, read
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.state import RunStatus

router = APIRouter(prefix="/api/private-access", tags=["operator"])
DB = Annotated[Session, Depends(session_scope)]
OPS = {"install": "install", "start": "start", "login": "login", "enable": "serve_on", "disable": "stop"}


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["install", "start", "login", "enable", "disable"]
    client_request_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    node_id: str | None = Field(default=None, max_length=128)
    origin: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def device_scope(self):
        if self.operation == "enable":
            from app.private_access import validated_tailnet_origin

            if not self.node_id or validated_tailnet_origin(self.origin) != self.origin:
                raise ValueError("Review the actual private device and HTTPS origin")
        elif self.node_id is not None or self.origin is not None:
            raise ValueError("Only enabling access selects a private device")
        return self


def authority(session, *, create=False, run=None):
    from app.private_access_accounts import authority as account_authority

    account = account_authority(session, run=run, mutation=create)
    if account is not None:
        return account
    from app.operator_auth import configured, stored_secret

    if not configured(session):
        raise HTTPException(409, "Set the operator password before private remote access")
    secret = stored_secret(session)
    revision = secret.get("authority_revision")
    if not revision and create:
        revision = secrets.token_hex(16)
        session.get(Setting, "operator_auth").value = {**secret, "authority_revision": revision}
    return revision


def native_payload(run):
    return {
        "run_id": run.id,
        "operation": OPS[run.parameters["operation"]],
        "permissions": ["manage_private_access"],
    }


def valid_run(session, run, *, locked=False):
    require(run.effective_permissions, "manage_private_access")
    state = lock(session, run=run).value if locked else read(session, run=run)
    if (
        run.executor_type != "private_access"
        or run.capability != "system.private_access"
        or run.task.intent != "operator.private_access"
        or run.task.agent_id
        or run.task.project_id
        or run.task.conversation_id
        or run.agent_id
        or run.project_id
        or run.conversation_id
        or run.parent_run_id
        or run.effective_permissions != ["manage_private_access"]
        or state.get("pending_run_id") != run.id
        or state.get("revision") != run.parameters.get("policy_revision")
        or not run.parameters.get("authority_revision")
        or authority(session, run=run) != run.parameters["authority_revision"]
        or run.parameters.get("operation") not in OPS
    ):
        raise ValueError("Private access authority changed; review a new operation")
    return state


@router.get("")
def status(session: DB):
    from app.data_access import ScopedSession
    from app.operator_auth import configured

    policy = read(session)
    rid = policy.get("pending_run_id")
    run = session.get(Run, rid) if rid else None
    result = {
        "revision": policy.get("revision", 0),
        "enabled": policy.get("enabled") is True,
        "approved_origin": policy.get("origin") if policy.get("enabled") is True else None,
        "run": run_dict(run) if run else None,
        **operation_facts(session, policy),
    }
    try:
        ready = bool(authority(session)) if isinstance(session, ScopedSession) else configured(session)
    except HTTPException:
        ready = False
    if not ready:
        return {**result, "available": False, "state": "password_required", "serving": False}
    # SQLite reads use BEGIN IMMEDIATE. Release that transaction before native
    # I/O so an unavailable service cannot stall unrelated API/worker requests.
    session.commit()
    try:
        native = RunnerClient(timeout=5).request("GET", "/v1/private-access")
        if isinstance(session, ScopedSession):
            # The native daemon identity can be its launching account's Run.
            # Shared service health never exposes process provenance or logs.
            public = {
                "available",
                "installed",
                "version",
                "state",
                "node_online",
                "node_id",
                "origin",
                "serving",
                "configuration",
                "owned",
                "login_required",
            }
            native = {key: value for key, value in native.items() if key in public}
        return {**native, **result}
    except (RunnerError, RunnerUnavailable):
        return {**result, "available": False, "state": "runner_unavailable", "serving": False}


@router.post("", status_code=202)
def enqueue(body: Action, session: DB):
    row = lock(session)
    revision = authority(session, create=True)
    state = dict(row.value)
    previous = session.get(Run, state["pending_run_id"]) if state.get("pending_run_id") else None
    request = body.model_dump(mode="json")
    if (
        previous
        and previous.parameters.get("request", {}).get("client_request_id") == request["client_request_id"]
    ):
        if previous.parameters["request"] != request:
            raise HTTPException(409, "Private access receipt has another scope")
        return run_dict(previous)
    facts = operation_facts(session, state)
    if facts["busy"]:
        raise HTTPException(409, "A private access operation is already active")
    if facts["needs_inspection"] and body.operation != "disable":
        raise HTTPException(409, "Disable the owned connection to resolve its uncertain operation first")
    if state.get("revision", 0) != body.expected_revision:
        raise HTTPException(409, "Private access changed; review current settings")
    number = state.get("revision", 0) + 1
    task = create_task(
        session,
        title=f"Private access: {body.operation}",
        prompt=f"Operator requested private access {body.operation}",
        capability="system.private_access",
    )
    task.intent = "operator.private_access"
    run = create_run(
        session,
        task,
        run_type="system",
        capability="system.private_access",
        executor_type="private_access",
        execution_target="host",
        permissions=["manage_private_access"],
        parameters={
            "operation": body.operation,
            "request": request,
            "authority_revision": revision,
            "policy_revision": number,
        },
        retry_class="inspect",
    )
    row.value = {
        **state,
        "revision": number,
        "pending_run_id": run.id,
        "password_required": True,
        **({"enabled": False, "origin": None} if body.operation == "disable" else {}),
    }
    session.commit()
    return run_dict(run)


@router.get("/actions/{run_id}/link")
def link(run_id: UUID, response: Response, session: DB):
    run = session.get(Run, str(run_id))
    if run is None:
        raise HTTPException(404, "Private access operation not found")
    from app.private_access_accounts import authority as account_authority

    account_authority(session, run=run, mutation=True)
    try:
        valid_run(session, run)
    except (ValueError, HTTPException):
        raise HTTPException(409, "Review the current private access operation") from None
    if run.parameters["operation"] not in {"login", "enable"}:
        raise HTTPException(409, "This action has no login link")
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    try:
        return RunnerClient(timeout=5).request("POST", "/v1/private-access/link", native_payload(run))
    except (RunnerError, RunnerUnavailable):
        raise HTTPException(409, "Interactive action is unavailable; check its Run") from None


def finish(session, run, result):
    row = lock(session, run=run)
    session.refresh(run)
    if run.status == "cancel_requested":
        raise ValueError("Private access was stopped before publication")
    state = valid_run(session, run, locked=True)
    phase = result.get("phase")
    if result.get("process_confirmed_gone") is not True:
        raise ValueError("Private action completion is not confirmed")
    service = result.get("service") or {}
    if phase not in {"succeeded", "login_required", "https_consent_required"}:
        mark_failed(
            session, run, "PrivateAccessNeedsInspection", "Private access did not reach the requested state"
        )
        return
    op = run.parameters["operation"]
    if op == "enable":
        selected = run.parameters["request"]
        if phase == "succeeded" and (
            not service.get("serving")
            or (service.get("node_id"), service.get("origin")) != (selected["node_id"], selected["origin"])
        ):
            raise ValueError("The approved private endpoint changed before publication")
        if phase == "succeeded":
            state = {**state, "enabled": True, "origin": selected["origin"], "node_id": selected["node_id"]}
    if op == "disable":
        state = {**state, "enabled": False, "origin": None, "node_id": None, "password_required": False}
    row.value = dict(state)
    run.metadata_json = {**run.metadata_json, "private_access_outcome": phase, "process_confirmed_gone": True}
    append_event(session, run.id, "private_access.completed", {"operation": op, "outcome": phase})
    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")


class PrivateAccessExecutor:
    name = "private_access"

    def execute(self, session, run):
        client = RunnerClient(timeout=10)
        try:
            if run.metadata_json.get("cancel_on_resume") and run.status != "cancel_requested":
                transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
            try:
                valid_run(session, run)
            except (ValueError, HTTPException):
                if not run.metadata_json.get("dispatch_attempted"):
                    raise
                if run.status != "cancel_requested":
                    transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
            if run.status == "cancel_requested" and not run.metadata_json.get("dispatch_attempted"):
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return
            if run.status != "cancel_requested":
                transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            if not run.metadata_json.get("dispatch_attempted"):
                run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
                session.commit()
                payload = native_payload(run)
                if run.parameters["operation"] == "enable":
                    payload.update(
                        node_id=run.parameters["request"]["node_id"],
                        origin=run.parameters["request"]["origin"],
                    )
                result = client.request("POST", "/v1/private-access/actions", payload)
            else:
                session.commit()
                result = client.request("POST", "/v1/private-access/inspect", native_payload(run))
            session.refresh(run)
            if run.status != "cancel_requested":
                transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            deadline = time.monotonic() + (200 if run.parameters["operation"] == "install" else 25)
            while True:
                session.refresh(run)
                canceled = run.status == "cancel_requested"
                try:
                    valid_run(session, run)
                except (ValueError, HTTPException):
                    canceled = True
                session.commit()
                if canceled:
                    result = client.request("POST", "/v1/private-access/cancel", native_payload(run))
                    if result.get("process_confirmed_gone"):
                        session.refresh(run)
                        run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
                        if run.status != "cancel_requested":
                            transition(
                                session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested"
                            )
                        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                        return
                if not canceled and result.get("phase") != "running":
                    break
                if time.monotonic() > deadline:
                    raise ValueError(
                        "Private operation exceeded its observation budget; inspect before retrying"
                    )
                time.sleep(0.1)
                result = client.request("POST", "/v1/private-access/inspect", native_payload(run))
            session.refresh(run)
            finish(session, run, result)
        except RunnerUnavailable:
            raise RunnerUnavailable("Private access could not be inspected; no action was replayed") from None
        except (ValueError, HTTPException, RunnerError):
            session.refresh(run)
            run.metadata_json = {
                **run.metadata_json,
                "cleanup_requires_inspection": bool(run.metadata_json.get("dispatch_attempted")),
            }
            if run.metadata_json.get("dispatch_attempted") and not run.metadata_json.get(
                "process_confirmed_gone"
            ):
                transition(
                    session,
                    run,
                    RunStatus.INTERRUPTED,
                    event_type="run.interrupted",
                    payload={"reason": "Private access requires inspection; no action was replayed"},
                )
            else:
                mark_failed(
                    session,
                    run,
                    "PrivateAccessNeedsInspection",
                    "Private access needs inspection; no automatic replay was attempted",
                )
