"""Version-two whole-recording plans, preserving the legacy segment contract."""

import math
import wave
from datetime import timedelta

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from app import whole_avatars as whole
from app.db import utcnow
from app.dependencies import depend_on
from app.models import Artifact, Run, RunEvent, Task
from app.resources import latest_resource_wait
from app.runs import create_run
from app.state import TERMINAL
from app.task_control import lock_task


def stage_ids(plan):
    return [plan[key] for key in ("speech_run_id", "planner_run_id", "whole_run_id") if plan.get(key)]


def final_run_id(plan):
    return plan.get("whole_run_id") if plan.get("version") == 2 else plan.get("compose_run_id")


def verify_sources(session, snapshots):
    try:
        whole.verify_snapshots(session, snapshots)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            409, "Whole-recording sources were removed or changed; inspect before continuing"
        ) from exc


def inspect_sources(session, portrait, audio, *, reference=False):
    try:
        return whole.inspect_sources(session, portrait, audio, reference=reference)
    except (OSError, ValueError, EOFError, wave.Error, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Choose an intact portrait and bounded canonical PCM recording") from exc


def animation_estimate(session, run):
    """Read-only projection of measured diffusion speed, excluding preparation.

    No hardware-specific timings or client-local timers. Saved events preserve
    the observation across API/browser restarts; finalization is not estimated.
    """
    if run is None or run.status != "running":
        return None
    progress = run.metadata_json.get("avatar_progress") or {}
    if progress.get("phase") != "animating":
        return None
    statement = select(RunEvent).where(
        RunEvent.run_id == run.id,
        RunEvent.event_type == "avatar.progress",
        RunEvent.payload["phase"].as_string() == "animating",
    )
    first = session.scalar(statement.order_by(RunEvent.sequence.asc()).limit(1))
    last = session.scalar(statement.order_by(RunEvent.sequence.desc()).limit(1))
    if first is None or last is None:
        return None
    initial, completed, total = (
        first.payload.get("completed_windows"),
        last.payload.get("completed_windows"),
        last.payload.get("total_windows"),
    )
    if (
        any(type(value) is not int for value in (initial, completed, total))
        or not 0 < initial < completed < total
        or completed - initial < 3
        or first.payload.get("total_windows") != total
        or progress.get("completed_windows") != completed
        or progress.get("total_windows") != total
    ):
        return None
    elapsed = (last.created_at - first.created_at).total_seconds()
    age = (utcnow() - last.created_at).total_seconds()
    if not 0 < elapsed <= whole.MAX_SECONDS:
        return None
    seconds_per_window = elapsed / (completed - initial)
    if not 0 <= age <= max(120, seconds_per_window * 3):
        return None  # Hide a stale estimate instead of counting down a stall.
    return math.ceil((total - completed) * seconds_per_window)


def view(session, task):
    plan = task.metadata_json["media_plan"]
    stages = [session.get(Run, identifier) for identifier in stage_ids(plan)]
    if not stages or any(run is None or run.task_id != task.id for run in stages):
        raise HTTPException(409, "Whole-recording stages require inspection")
    active = [run for run in stages if run.status not in TERMINAL]
    failed = next((run for run in stages if run.status in {"failed", "interrupted", "canceled"}), None)
    generation = session.get(Run, plan.get("whole_run_id")) if plan.get("whole_run_id") else None
    stopping = bool(task.metadata_json.get("stop_requested_at"))
    if generation and generation.status == "succeeded" and plan.get("final_artifact_id"):
        status = "succeeded"
    elif stopping:
        status = "cancel_requested" if active else "canceled"
    elif failed:
        status = "failed"
    elif generation and generation.status in {"claimed", "preparing", "running"}:
        status = "generating"
    elif generation:
        status = "queued"
    else:
        status = "preparing"
    observation = plan.get("observed_input")
    return {
        "task_id": task.id,
        "request": plan["request"],
        "revision": plan["revision"],
        "kind": "avatar",
        "mode": "whole_recording",
        "status": status,
        "duration_seconds": observation["samples"] / observation["sample_rate"] if observation else None,
        "completed_stages": sum(run.status == "succeeded" for run in stages),
        "total_stages": len(stages),
        "stage_run_ids": [run.id for run in stages],
        "whole_run_id": plan.get("whole_run_id"),
        # Legacy projections retain their type without inventing segment or
        # composition Runs. Whole-aware UI uses the real stage counts above.
        "completed_segments": 0,
        "total_segments": 0,
        "running_segments": 0,
        "queued_segments": 0,
        "active_segments": [],
        "scenes": [],
        "preview_artifact_id": None,
        "active_run_ids": [run.id for run in active],
        "native_progress": generation.metadata_json.get("avatar_progress") if generation else None,
        "estimated_animation_seconds": animation_estimate(session, generation),
        "resource_wait": latest_resource_wait(active),
        "final_artifact_id": plan.get("final_artifact_id"),
        "result_geometry": {"width": observation["width"], "height": observation["height"], "fps": 25}
        if observation
        else None,
        "resume_allowed": not active
        and not task.agent_id
        and status in {"failed", "canceled"}
        and plan["revision"] < 20,
        "error_message": failed.error_message if failed else "",
    }


def publish(
    session,
    body,
    *,
    task=None,
    parent_run_id=None,
    execution_deadline_at=None,
    observed_profile=None,
    appearance_snapshot=None,
):
    from app.media_jobs import FullAvatarRequest, execution_budget

    original = body.model_dump(mode="json")
    if task is None:
        existing = session.get(Task, str(body.client_request_id))
        if existing:
            plan = existing.metadata_json.get("media_plan", {})
            if plan.get("version") != 2 or plan.get("request") != original:
                raise HTTPException(409, "Request ID belongs to another media intent")
            return view(session, existing)
    prior = task.metadata_json.get("media_plan", {}) if task else {}
    handoff = bool(prior)
    if handoff:
        if prior.get("version") != 2 or prior.get("kind") != "avatar":
            raise HTTPException(409, "Whole-recording publication belongs to another plan")
        if prior.get("execution_deadline_at") != execution_deadline_at:
            raise HTTPException(409, "Whole-recording handoff cannot replace its original deadline")
        expected = FullAvatarRequest.model_validate(
            {**prior["request"], "audio_artifact_id": body.audio_artifact_id, "speech_text": None}
        )
        planner, speech, audio = (
            session.get(Run, prior.get("planner_run_id")) if prior.get("planner_run_id") else None,
            session.get(Run, prior.get("speech_run_id")) if prior.get("speech_run_id") else None,
            session.get(Artifact, str(body.audio_artifact_id)),
        )
        if (
            body != expected
            or planner is None
            or planner.id != parent_run_id
            or planner.task_id != task.id
            or planner.executor_type != "avatar_media_plan"
            or planner.parameters.get("request") != prior["request"]
            or planner.parameters.get("execution_deadline_at") != execution_deadline_at
            or speech is None
            or speech.status != "succeeded"
            or speech.task_id != task.id
            or audio is None
            or audio.run_id != speech.id
            or audio.trashed_at is not None
        ):
            raise HTTPException(409, "Whole-recording speech handoff changed its reviewed scope")
        if prior.get("whole_run_id"):
            return view(session, task)
        # The portrait and voice reference were frozen before generating speech.
        verify_sources(session, prior["initial_sources"])
        request = prior["request"]
        selected = whole.frozen_recipe(prior["whole_recipe"])
        deadline = execution_deadline_at
    else:
        request = original
        selected = (
            whole.frozen_recipe(appearance_snapshot["whole_recipe"])
            if appearance_snapshot is not None
            else None
        )
        deadline = execution_deadline_at or (utcnow() + timedelta(seconds=whole.MAX_SECONDS)).isoformat()
    budget = execution_budget(deadline)
    profile = whole.capabilities() if observed_profile is None else observed_profile
    recipe = whole.verify_recipe(profile, selected if selected is not None else profile.get("recipe"))
    inputs, observation = inspect_sources(
        session, body.image_artifact_id, body.audio_artifact_id, reference=body.speech_text is not None
    )
    if task is None:
        task = Task(
            id=str(body.client_request_id),
            title=body.prompt[:80],
            prompt=body.prompt,
            capability="avatar.long",
            metadata_json={},
        )
        session.add(task)
        session.flush()
    lock_task(session, task)
    revision = prior.get("revision", 1)
    plan = {
        "version": 2,
        "revision": revision,
        "kind": "avatar",
        "mode": "whole_recording",
        "request": request,
        "whole_recipe": recipe,
        **budget,
        "initial_sources": prior.get("initial_sources", inputs),
        "whole_run_id": None,
        "final_artifact_id": None,
        "speech_run_id": prior.get("speech_run_id"),
        "planner_run_id": prior.get("planner_run_id"),
        "canonical_audio_id": None,
        "observed_input": None,
    }
    if body.speech_text is not None:
        from app.audio import SpeechRequest, create_audio_run

        speech = create_audio_run(
            session,
            SpeechRequest(text=body.speech_text, reference_artifact_id=body.audio_artifact_id, gpu=body.gpu),
            task=task,
            parent_run_id=parent_run_id,
        )
        speech.parameters = {**speech.parameters, **budget, "whole_avatar_sources": inputs}
        planner = create_run(
            session,
            task,
            run_type="video",
            capability="avatar.plan",
            executor_type="avatar_media_plan",
            execution_target="container",
            parent_run_id=parent_run_id,
            operation_key=f"media:{revision}:plan:attempt:1",
            parameters={**budget, "speech_run_id": speech.id, "request": request},
            permissions=["filesystem_read", "workspace_write"],
            retry_class="inspect",
        )
        depend_on(session, planner, speech)
        plan.update(speech_run_id=speech.id, planner_run_id=planner.id)
    else:
        generation = whole.create_whole_run(
            session,
            body,
            task=task,
            parent_run_id=parent_run_id,
            recipe=recipe,
            observed_profile=profile,
            execution_deadline_at=deadline,
        )
        generation.operation_key = f"media:{revision}:whole:attempt:1"
        generation.parameters = {**generation.parameters, "internal_media": True}
        plan.update(
            whole_run_id=generation.id,
            canonical_audio_id=str(body.audio_artifact_id),
            observed_input=observation,
        )
    task.metadata_json = {**task.metadata_json, "media_request": request, "media_plan": plan}
    task.updated_at = utcnow()
    session.flush()
    return view(session, task)


def resume(session, task, body, *, receipts, key):
    from app.media_jobs import save_resume
    from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable

    plan = task.metadata_json["media_plan"]
    profile = whole.capabilities()
    whole.verify_recipe(profile, plan["whole_recipe"])
    selected = [session.get(Run, identifier) for identifier in stage_ids(plan)]
    for run in selected:
        if (
            run.status != "succeeded"
            and run.metadata_json.get("dispatch_attempted")
            and not run.metadata_json.get("process_confirmed_gone")
        ):
            try:
                inspected = RunnerClient().inspect_process(run.id)
            except (RunnerError, RunnerUnavailable) as exc:
                raise HTTPException(409, "Inspect the preceding owned process before resuming") from exc
            if inspected.get("alive", True) or inspected.get("completion_pending"):
                raise HTTPException(409, "The preceding owned process is still active")
    revision = plan["revision"] + 1
    deadline = (utcnow() + timedelta(seconds=whole.MAX_SECONDS)).isoformat()
    task.metadata_json = {
        key: value for key, value in task.metadata_json.items() if key != "stop_requested_at"
    }

    def clone(source, role, parameters):
        return create_run(
            session,
            task,
            run_type=source.run_type,
            capability=source.capability,
            executor_type=source.executor_type,
            execution_target=source.execution_target,
            operation_key=f"media:{revision}:{role}:attempt:1",
            parent_run_id=source.id,
            permissions=list(source.effective_permissions),
            retry_class="inspect",
            requested_gpu=source.requested_gpu,
            requested_resources=dict(source.requested_resources),
            parameters={**parameters, "execution_deadline_at": deadline},
        )

    updated = {**plan, "revision": revision, "execution_deadline_at": deadline, "final_artifact_id": None}
    if plan.get("whole_run_id"):
        source = session.get(Run, plan["whole_run_id"])
        verify_sources(session, source.parameters["whole_inputs"])
        child = clone(source, "whole", source.parameters)
        updated["whole_run_id"] = child.id
    else:
        verify_sources(session, plan["initial_sources"])
        speech, planner = session.get(Run, plan["speech_run_id"]), session.get(Run, plan["planner_run_id"])
        if speech.status == "succeeded":
            audio = session.scalar(
                select(Artifact).where(
                    Artifact.run_id == speech.id,
                    Artifact.artifact_type == "audio",
                    Artifact.trashed_at.is_(None),
                )
            )
            if audio is None:
                raise HTTPException(409, "Restore the completed speech artifact before resuming")
            inspect_sources(session, plan["request"]["image_artifact_id"], audio.id)
        else:
            speech = clone(speech, "speech", speech.parameters)
        planner = clone(planner, "plan", {**planner.parameters, "speech_run_id": speech.id})
        depend_on(session, planner, speech)
        updated.update(speech_run_id=speech.id, planner_run_id=planner.id)
    return save_resume(session, task, plan, updated, receipts, key, body)
