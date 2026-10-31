"""A durable film → effects → editable mix dependency graph; no new native API."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.conversation_effects import EffectsScope, preflight, request
from app.dependencies import depend_on
from app.effects import available_profile, create_effects_run, video_snapshot
from app.models import Artifact, Run
from app.permissions import require
from app.runs import create_run, transition
from app.state import TERMINAL, RunStatus


def enqueue(session, root, source_id, profile, renderer, *, revision=1):
    require(root.effective_permissions, "filesystem_read")
    require(root.effective_permissions, "workspace_write")
    scope = EffectsScope.model_validate(root.parameters["effects"])
    if scope.video_artifact_id is not None or not scope.prompt:
        raise ValueError("New-film sound requires its reviewed description and generated source")
    source = session.get(Run, source_id)
    if (
        source is None
        or source.task_id != root.task_id
        or source.executor_type not in {"wan_video", "media_compose"}
    ):
        raise ValueError("Sound source does not belong to this film task")
    operation = f"film-sound:{revision}:prepare"
    prior = session.scalar(select(Run).where(Run.task_id == root.task_id, Run.operation_key == operation))
    if prior is not None:
        if (
            prior.parameters.get("source_run_id") != source_id
            or prior.parent_run_id != root.id
            or prior.parameters.get("scope") != scope.model_dump(mode="json")
            or prior.parameters.get("profile") != profile
            or prior.parameters.get("renderer") != renderer
        ):
            raise ValueError("Sound preparation receipt belongs to a different film")
        return prior
    child = create_run(
        session,
        root.task,
        run_type="audio",
        capability="audio.effects.prepare",
        executor_type="film_sound_prepare",
        execution_target="container",
        operation_key=operation,
        parent_run_id=root.id,
        retry_class="safe",
        permissions=["filesystem_read", "workspace_write"],
        parameters={
            "source_run_id": source.id,
            "root_run_id": root.id,
            "scope": scope.model_dump(mode="json"),
            "profile": profile,
            "renderer": renderer,
        },
    )
    depend_on(session, child, source)
    root.task.metadata_json = {
        **root.task.metadata_json,
        "soundtrack_plan": {
            "version": 1,
            "revision": revision,
            "root_run_id": root.id,
            "source_run_id": source.id,
            "prepare_run_id": child.id,
        },
    }
    return child


class FilmSoundExecutor:
    name = "film_sound_prepare"

    def execute(self, session, run):
        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        root = session.get(Run, run.parameters["root_run_id"])
        source = session.get(Run, run.parameters["source_run_id"])
        plan = run.task.metadata_json.get("soundtrack_plan", {})
        if (
            root is None
            or source is None
            or root.task_id != run.task_id
            or source.task_id != run.task_id
            or source.status != "succeeded"
            or root.parameters.get("effects") != run.parameters["scope"]
            or plan.get("prepare_run_id") != run.id
            or plan.get("source_run_id") != source.id
        ):
            raise ValueError("The reviewed film sound graph changed or is unfinished")
        films = list(
            session.scalars(
                select(Artifact).where(Artifact.run_id == source.id, Artifact.artifact_type == "video")
            )
        )
        if (
            len(films) != 1
            or films[0].metadata_json.get("partial")
            or films[0].metadata_json.get("internal_media")
        ):
            raise ValueError("Sound requires exactly one verified final film")
        film = films[0]
        video_snapshot(session, film.id, verify=True)
        from app.effects import capabilities

        current = preflight(session, run, capabilities)
        if not available_profile(current) or any(
            current.get(key) != run.parameters["profile"].get(key)
            for key in ("observation", "environment_id")
        ):
            raise ValueError("The admitted sound runtime changed; inspect setup before retrying")
        scope = EffectsScope.model_validate(run.parameters["scope"])
        if scope.preview_mode == "mix":
            from app.timelines import capabilities as timeline_capabilities

            renderer = preflight(session, run, timeline_capabilities)
            if not renderer.get("available") or renderer.get("observation") != run.parameters["renderer"].get(
                "observation"
            ):
                raise ValueError("The admitted film editor changed; inspect setup before retrying")
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        # All external observations are complete. Child, receipt and final state
        # commit together; Task Stop is serialized by create_run's task lock.
        values = scope.model_copy(update={"video_artifact_id": UUID(film.id)}).model_dump(mode="json")
        child = create_effects_run(
            session,
            request({"content": scope.prompt, "effects": values}),
            task=run.task,
            parent_run_id=run.id,
            observed_profile=current,
        )
        if scope.preview_mode == "mix":
            child.parameters = {
                **child.parameters,
                "effects_mix": scope.model_dump(
                    mode="json", include={"preview_mode", "original_gain", "effects_gain"}
                ),
                "effects_mix_renderer": renderer,
            }
        depend_on(session, child, run)
        run.metadata_json = {**run.metadata_json, "effects_run_id": child.id, "source_artifact_id": film.id}
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


def stages(session, task):
    plan = task.metadata_json.get("soundtrack_plan")
    if not plan:
        return []
    prep = session.get(Run, plan["prepare_run_id"])
    result = [prep] if prep else []
    stem = session.get(Run, prep.metadata_json.get("effects_run_id", "")) if prep else None
    if stem and stem.task_id == task.id and stem.parent_run_id == prep.id:
        result.append(stem)
        preview = session.get(Run, stem.metadata_json.get("effects_preview_run_id", ""))
        if preview and preview.task_id == task.id and preview.parent_run_id == stem.id:
            result.append(preview)
    return result


def overlay(session, task, base):
    if not task.metadata_json.get("soundtrack_plan"):
        return base
    runs = stages(session, task)
    active = [r.id for r in runs if r.status not in TERMINAL]
    failed = next((r for r in runs if r.status in {"failed", "interrupted", "canceled"}), None)
    final = None
    if len(runs) == 3 and runs[-1].status == "succeeded":
        films = list(
            session.scalars(
                select(Artifact).where(
                    Artifact.run_id == runs[-1].id,
                    Artifact.artifact_type == "video",
                    Artifact.trashed_at.is_(None),
                )
            )
        )
        if len(films) == 1 and not films[0].purged_at and not films[0].purge_run_id:
            final = films[0].id
    stopping = task.metadata_json.get("stop_requested_at")
    active_ids = list(dict.fromkeys([*base["active_run_ids"], *active]))
    missing_result = len(runs) == 3 and runs[-1].status == "succeeded" and final is None
    status = (
        ("cancel_requested" if active_ids else "canceled")
        if stopping
        else "failed"
        if failed or missing_result
        else base["status"]
    )
    if base["status"] == "succeeded" and not stopping and not failed and not missing_result:
        status = "succeeded" if final else "composing" if len(runs) == 3 else "generating"
    return {
        **base,
        "status": status,
        "active_run_ids": active_ids,
        "final_artifact_id": final if status == "succeeded" else None,
        "soundtrack_status": "succeeded"
        if final
        else "failed"
        if failed
        else "mixing"
        if len(runs) == 3
        else "generating"
        if len(runs) == 2
        else "waiting_for_film",
        "resume_allowed": not active_ids and status in {"failed", "canceled"},
        "error_message": failed.error_message
        if failed
        else "The completed sound film is unavailable. Inspect its retained sources before resuming."
        if missing_result
        else base["error_message"],
    }


def resume_sound(session, task, body, receipts, key, base):
    """Explicit recovery repeats sound only; completed video is never re-generated."""
    plan = task.metadata_json["soundtrack_plan"]
    previous = stages(session, task)
    from app.runner_client import RunnerClient

    for run in previous:
        if run.status not in TERMINAL:
            raise HTTPException(409, "Sound work is still active")
        if (
            run.status != "succeeded"
            and run.metadata_json.get("dispatch_attempted")
            and not run.metadata_json.get("process_confirmed_gone")
        ):
            observed = RunnerClient().inspect_process(run.id)
            if observed.get("alive", True) or observed.get("completion_pending"):
                raise HTTPException(409, "An owned sound process still requires inspection")
    old = session.get(Run, plan["prepare_run_id"])
    root = session.get(Run, plan["root_run_id"])
    task.metadata_json = {k: v for k, v in task.metadata_json.items() if k != "stop_requested_at"}
    task.metadata_json = {
        **task.metadata_json,
        "soundtrack_revisions": [*task.metadata_json.get("soundtrack_revisions", []), plan],
    }
    enqueue(
        session,
        root,
        plan["source_run_id"],
        old.parameters["profile"],
        old.parameters["renderer"],
        revision=plan["revision"] + 1,
    )
    from app.media_jobs import save_resume

    updated = {**base, "revision": base["revision"] + 1}
    return save_resume(session, task, base, updated, receipts, key, body)
