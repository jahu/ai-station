"""Durable approvals. A pending record parks a Run until the user grants or denies it."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.events import append_event
from app.models import Approval, Run
from app.runs import run_dict, transition
from app.state import RunStatus


def pending_approval(session: Session, run_id: str) -> Approval | None:
    return session.scalar(
        select(Approval)
        .where(Approval.run_id == run_id, Approval.resolution == "pending")
        .order_by(Approval.requested_at.desc())
        .limit(1)
    )


def latest_approval(session: Session, run_id: str) -> Approval | None:
    return session.scalar(
        select(Approval).where(Approval.run_id == run_id).order_by(Approval.requested_at.desc()).limit(1)
    )


def run_public(session: Session, run: Run) -> dict:
    payload = run_dict(run)
    approval = latest_approval(session, run.id)
    if approval is not None:
        from app.serialize import approval_dict

        payload["approval"] = approval_dict(approval)
    from app.agent_workflow import workflow_view

    workflow = workflow_view(session, run)
    if workflow is not None:
        payload["workflow"] = workflow
    from app.schedule import retry_view

    payload["retry"] = retry_view(session, run)
    return payload


def request_run_approval(session: Session, run: Run, *, action: str, reason: str, payload: dict) -> Approval:
    if run.status != RunStatus.QUEUED.value:
        raise ValueError("Approvals can only park a queued Run")
    approval = Approval(
        run_id=run.id,
        action=action,
        reason=reason,
        risk="medium",
        payload=payload,
        resolution="pending",
    )
    session.add(approval)
    session.flush()
    run.parameters = {**run.parameters, "approval_id": approval.id}
    transition(
        session,
        run,
        RunStatus.WAITING_FOR_APPROVAL,
        event_type="approval.requested",
        payload={"approval_id": approval.id, "action": action},
    )
    return approval


def dismiss_pending(session: Session, run: Run, resolution: str = "canceled") -> None:
    approval = pending_approval(session, run.id)
    if approval is None:
        return
    approval.resolution = resolution
    approval.resolved_at = utcnow()
    append_event(
        session,
        run.id,
        f"approval.{resolution}",
        {"approval_id": approval.id, "action": approval.action},
    )


def resolve_run_approval(session: Session, run: Run, resolution: str) -> Run:
    if resolution not in {"granted", "denied"}:
        raise ValueError("Approval resolution must be granted or denied")
    if run.status != RunStatus.WAITING_FOR_APPROVAL.value:
        raise ValueError("This Run is not waiting for approval")
    approval = pending_approval(session, run.id)
    if approval is None:
        raise ValueError("No pending approval exists for this Run")
    approval.resolution = resolution
    approval.resolved_at = utcnow()
    append_event(
        session,
        run.id,
        f"approval.{resolution}",
        {"approval_id": approval.id, "action": approval.action, "by": "user"},
    )
    if resolution == "denied":
        transition(
            session, run, RunStatus.CANCELED, event_type="run.canceled", payload={"approval": "denied"}
        )
        return run
    fixed_media = (
        run.executor_type == "agent_media"
        and (run.parameters.get("definition", {}).get("media") or {}).get("description_source", "fixed")
        == "fixed"
    )
    if run.executor_type != "agent_workflow" and not fixed_media:
        from app.llama import prepare_consumer

        prepare_consumer(session, run)
    transition(session, run, RunStatus.QUEUED, event_type="run.requeued", payload={"approval": "granted"})
    return run
