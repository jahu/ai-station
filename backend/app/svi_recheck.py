"""Metadata-only recurrent model recheck through the existing model-install Run."""

import json
import tempfile
from pathlib import Path

from fastapi import HTTPException

from app.artifacts import register_file
from app.events import append_event
from app.models import User
from app.runs import mark_failed, transition
from app.state import RunStatus
from app.task_control import lock_task
from app.video_models import frozen_model, profile_for, same_model


def execute(session, run, definition):
    claim = run.worker_id, run.claimed_at
    if not same_model(frozen_model(session, definition.id, recheck=True), run.parameters["svi_model"]):
        raise ValueError("The recurrent bundle changed after recheck was queued")
    transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
    transition(
        session, run, RunStatus.RUNNING, event_type="executor.started", payload={"mode": "metadata_only"}
    )
    session.commit()
    error = None
    try:
        profile = profile_for(session, definition.id, recheck=True)
    except HTTPException as exc:
        error = str(exc.detail)
        profile = None
    lock_task(session, run.task)
    session.refresh(run)
    if (run.worker_id, run.claimed_at) != claim:
        session.rollback()
        return "done"
    if run.status not in {"running", "cancel_requested"}:
        return "done"
    if run.status == "cancel_requested" or run.task.metadata_json.get("stop_requested_at"):
        if run.status != "cancel_requested":
            transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        return "done"
    if run.owner_id:
        owner = session.get(User, run.owner_id, populate_existing=True, with_for_update=True)
        if owner is None or not owner.enabled or not owner.is_admin:
            raise ValueError("Recurrent model recheck administrator authority changed")
    session.refresh(definition)
    if not same_model(frozen_model(session, definition.id, recheck=True), run.parameters["svi_model"]):
        raise ValueError("The recurrent bundle changed before recheck publication")
    if error:
        mark_failed(session, run, "RecurrentModelUnavailable", error)
        return "done"
    report = {
        "definition_id": definition.id,
        "managed_runtime": profile["managed_runtime"],
        "component_count": 6,
        "metadata_only": True,
        "weights_rehashed_now": False,
        "inference_tested_now": False,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json") as output:
        json.dump(report, output)
        output.flush()
        register_file(
            session,
            source=Path(output.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="recurrent-model-recheck.json",
            run_id=run.id,
            metadata={"metadata_only": True, "downloaded": False, "pulled": False},
        )
    definition.status = "registered"
    append_event(session, run.id, "models.install", report)
    run.summary = "The six registered components and exact prepared recurrent engine remain available. No model was downloaded or loaded."
    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
    return "done"
