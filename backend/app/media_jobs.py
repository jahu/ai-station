"""Durable segmented video jobs built from existing Runs, dependencies and artifacts."""

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope, utcnow
from app.dependencies import depend_on
from app.host_media_executor import HostMediaExecutor
from app.media_plan import duration_frames, timeline
from app.models import Artifact, Run, Task
from app.paths import safe_join
from app.resources import RESOURCE_WAIT_KEY
from app.runs import create_run, run_dict
from app.state import TERMINAL
from app.task_control import cancel_task, lock_task
from app.video import VideoRequest, capabilities, create_video_run

router = APIRouter(prefix="/api/media/jobs", tags=["media jobs"])
DB = Annotated[Session, Depends(session_scope)]


class VideoScene(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=1000)
    duration_seconds: StrictInt = Field(ge=1, le=60)


class LongVideoRequest(VideoRequest):
    client_request_id: UUID
    duration_seconds: StrictInt = Field(default=15, ge=1, le=60)
    composition_mode: Literal["continuous", "shots"] = "continuous"
    scenes: list[VideoScene] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def no_frames(self):
        if "frames" in self.model_fields_set:
            raise ValueError("Choose duration or short-clip frames, not both")
        if self.scenes is not None:
            if self.composition_mode != "shots":
                raise ValueError("Individual scenes require an independent shot sequence")
            if sum(scene.duration_seconds for scene in self.scenes) != self.duration_seconds:
                raise ValueError("Scene durations must add up to the requested film duration")
            if any(len(self.prompt + "\n\n" + scene.prompt) > 2000 for scene in self.scenes):
                raise ValueError("Shared instructions and each scene must fit 2000 characters together")
        return self


def video_request(body):
    # Preserve receipt identity for requests saved before storyboards existed.
    return body.model_dump(mode="json", exclude={"frames"} | ({"scenes"} if body.scenes is None else set()))


def job(session, task_id):
    task = session.get(Task, str(task_id))
    if not task or not task.metadata_json.get("media_plan"):
        raise HTTPException(404, "Media job not found")
    return task


def publish_video(session, body, *, task=None, parent_run_id=None):
    prior = session.get(Task, str(body.client_request_id)) if task is None else None
    if prior:
        expected = video_request(body)
        if prior.metadata_json.get("media_plan", {}).get("request") != expected:
            raise HTTPException(409, "Request ID already belongs to a different media job")
        return job_view(session, prior)
    if task is None:
        task = Task(
            id=str(body.client_request_id),
            title=body.prompt[:80],
            prompt=body.prompt,
            capability="video.long",
            metadata_json={},
        )
        session.add(task)
        session.flush()
    lock_task(session, task)
    if task.metadata_json.get("media_plan"):
        return job_view(session, task)
    observed_profile = capabilities()
    reservation = observed_profile.get("memory_estimate_mib", 16384)
    timing = timeline(
        frames=duration_frames(body.duration_seconds, 24),
        fps=24,
        seed=body.seed,
        mode=body.composition_mode,
        scene_frames=[scene.duration_seconds * 24 for scene in body.scenes] if body.scenes else None,
    )
    scene_index = 0
    scene_end = body.scenes[0].duration_seconds * 24 if body.scenes else 0
    runs = []
    previous = None
    for segment in timing.segments:
        if body.scenes:
            while segment.start_frame >= scene_end:
                scene_index += 1
                scene_end += body.scenes[scene_index].duration_seconds * 24
        settings = VideoRequest.model_validate(
            {
                **body.model_dump(
                    exclude={"duration_seconds", "composition_mode", "frames", "client_request_id", "scenes"}
                ),
                "prompt": body.prompt + "\n\n" + body.scenes[scene_index].prompt
                if body.scenes
                else body.prompt,
                "frames": segment.generated_frames,
                "seed": segment.seed,
            }
        )
        run = create_video_run(session, settings, task=task, parent_run_id=parent_run_id)
        run.requested_resources = {"ram_mib": reservation}
        run.operation_key = f"media:1:segment:{segment.index}:attempt:1"
        run.parameters = {
            **run.parameters,
            "media_segment": segment.model_dump(),
            "internal_media": True,
            "profile_observation": observed_profile.get("profile_observation"),
        }
        if body.scenes:
            run.parameters = {**run.parameters, "scene_index": scene_index}
        if previous and body.composition_mode == "continuous":
            run.parameters = {**run.parameters, "previous_video_run_id": previous.id}
            depend_on(session, run, previous)
        runs.append(run)
        previous = run
    compose = create_run(
        session,
        task,
        run_type="video",
        capability="media.compose",
        executor_type="media_compose",
        execution_target="host",
        operation_key="media:1:compose:attempt:1",
        parameters={
            "stage_run_ids": [run.id for run in runs],
            "timeline": timing.model_dump(mode="json"),
            "width": body.width,
            "height": body.height,
            "backend": "wan2.2-5b",
            "composition_mode": body.composition_mode,
            **(
                {"prompt": body.prompt, "scenes": [scene.model_dump() for scene in body.scenes]}
                if body.scenes
                else {}
            ),
        },
        permissions=["filesystem_read", "workspace_write"],
        retry_class="inspect",
        parent_run_id=parent_run_id,
    )
    for run in runs:
        depend_on(session, compose, run)
    task.metadata_json = {
        **task.metadata_json,
        "media_plan": {
            "version": 1,
            "profile_observation": observed_profile.get("profile_observation"),
            "revision": 1,
            "kind": "video",
            "mode": body.composition_mode,
            "timing": timing.model_dump(mode="json"),
            "segment_run_ids": [r.id for r in runs],
            "compose_run_id": compose.id,
            "request": video_request(body),
            "final_artifact_id": None,
        },
    }
    session.flush()
    return job_view(session, task)


def preview_artifact(session, plan):
    return session.scalar(
        select(Artifact.id)
        .join(Run, Run.id == Artifact.run_id)
        .where(
            Artifact.run_id.in_(plan.get("segment_run_ids", [])),
            Artifact.artifact_type == "video",
            Artifact.trashed_at.is_(None),
            Run.status == "succeeded",
        )
        .order_by(Run.finished_at.desc(), Artifact.created_at.desc(), Artifact.id.desc())
        .limit(1)
    )


def job_view(session, task):
    plan = task.metadata_json["media_plan"]
    if plan.get("timing") is None:
        ids = [plan["speech_run_id"], plan["planner_run_id"]]
        stages = list(session.scalars(select(Run).where(Run.id.in_(ids))))
        failed = next((r for r in stages if r.status in {"failed", "interrupted", "canceled"}), None)
        active = [r.id for r in stages if r.status not in TERMINAL]
        return {
            "task_id": task.id,
            "request": plan["request"],
            "preview_artifact_id": None,
            "revision": plan["revision"],
            "kind": "avatar",
            "mode": "continuous",
            "status": "cancel_requested"
            if task.metadata_json.get("stop_requested_at") and active
            else "canceled"
            if task.metadata_json.get("stop_requested_at")
            else "failed"
            if failed
            else "preparing",
            "duration_seconds": None,
            "completed_segments": 0,
            "total_segments": 0,
            "running_segments": 0,
            "queued_segments": 0,
            "active_segments": [],
            "active_run_ids": active,
            "final_artifact_id": None,
            "resume_allowed": not active and bool(failed or task.metadata_json.get("stop_requested_at")),
            "error_message": failed.error_message if failed else "",
        }
    ids = [*plan["segment_run_ids"], plan["compose_run_id"]]
    stages = {r.id: r for r in session.scalars(select(Run).where(Run.id.in_(ids)))}
    compose = stages[plan["compose_run_id"]]
    active = [r for r in stages.values() if r.status not in TERMINAL]
    stopping = bool(task.metadata_json.get("stop_requested_at"))
    if compose.status == "succeeded" and plan.get("final_artifact_id"):
        status = "succeeded"
    elif stopping:
        status = "cancel_requested" if active else "canceled"
    elif any(r.status in {"failed", "interrupted", "canceled"} for r in stages.values()):
        status = "failed"
    elif compose.status in {"claimed", "preparing", "running"}:
        status = "composing"
    elif any(r.status == "running" for r in stages.values()):
        status = "generating"
    else:
        status = "queued"
    return {
        "task_id": task.id,
        "request": plan["request"],
        "preview_artifact_id": preview_artifact(session, plan),
        "revision": plan["revision"],
        "kind": plan["kind"],
        "mode": plan["mode"],
        "scenes": scene_progress(plan, stages),
        "status": status,
        "duration_seconds": plan["timing"]["target_frames"] / plan["timing"]["fps"],
        "completed_segments": sum(stages[rid].status == "succeeded" for rid in plan["segment_run_ids"]),
        "total_segments": len(plan["segment_run_ids"]),
        "running_segments": sum(stages[rid].status == "running" for rid in plan["segment_run_ids"]),
        "queued_segments": sum(stages[rid].status == "queued" for rid in plan["segment_run_ids"]),
        "active_segments": [
            {"run_id": rid, "index": index, "status": stages[rid].status, "gpu": stages[rid].actual_gpu}
            for index, rid in enumerate(plan["segment_run_ids"])
            if stages[rid].status not in TERMINAL and stages[rid].status != "queued"
        ],
        "active_run_ids": [r.id for r in active],
        "final_artifact_id": plan.get("final_artifact_id"),
        "resume_allowed": not active and status in {"failed", "canceled"},
        "error_message": next((r.error_message for r in stages.values() if r.error_message), ""),
    }


def scene_progress(plan, stages):
    result = []
    for index, scene in enumerate(plan["request"].get("scenes") or []):
        selected = [
            stages[rid]
            for rid in plan["segment_run_ids"]
            if stages[rid].parameters.get("scene_index") == index
        ]
        states = {run.status for run in selected}
        status = (
            "succeeded"
            if states == {"succeeded"}
            else "failed"
            if states & {"failed", "interrupted"}
            else "cancel_requested"
            if "cancel_requested" in states
            else "canceled"
            if "canceled" in states
            else "running"
            if states & {"running", "preparing", "claimed"}
            else "queued"
        )
        result.append(
            {
                **scene,
                "index": index,
                "status": status,
                "completed_segments": sum(r.status == "succeeded" for r in selected),
                "total_segments": len(selected),
            }
        )
    return result


@router.post("/video", status_code=202)
def generate(body: LongVideoRequest, session: DB):
    if not capabilities().get("available"):
        raise HTTPException(409, "Configure the existing local Wan runtime")
    result = publish_video(session, body)
    session.commit()
    return result


@router.get("/{task_id}")
def detail(task_id: UUID, session: DB):
    return job_view(session, job(session, task_id))


@router.get("/{task_id}/stages")
def stages(task_id: UUID, session: DB, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
    task = job(session, task_id)
    return [
        run_dict(run)
        for run in session.scalars(
            select(Run)
            .where(Run.task_id == task.id)
            .order_by(Run.created_at, Run.id)
            .offset(offset)
            .limit(limit)
        )
    ]


@router.post("/{task_id}/cancel")
def stop(task_id: UUID, session: DB):
    task = job(session, task_id)
    cancel_task(session, task)
    session.commit()
    return job_view(session, task)


class CompositionExecutor(HostMediaExecutor):
    name = "media_compose"
    requires_gpu = False
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"

    def _start(self, runner, run, allocated, output):
        from app.db import session_factory

        clips = []
        parents = []
        with session_factory()() as session:
            for index, rid in enumerate(run.parameters["stage_run_ids"]):
                source = session.get(Run, rid)
                artifact = session.scalar(
                    select(Artifact).where(Artifact.run_id == rid, Artifact.artifact_type == "video")
                )
                if (
                    not source
                    or source.status != "succeeded"
                    or not artifact
                    or artifact.trashed_at is not None
                ):
                    raise ValueError("A successful adopted segment is unavailable")
                segment = run.parameters["timeline"]["segments"][index]
                clips.append(
                    {
                        "relative_path": artifact.relative_path,
                        "sha256": artifact.sha256,
                        "size_bytes": artifact.size_bytes,
                        "expected_frames": segment["generated_frames"],
                        "frames": segment["output_frames"],
                        "first_frame": segment.get("first_frame", 0),
                    }
                )
                parents.append(artifact.id)
        sound = None
        if run.parameters.get("canonical_audio_id"):
            with session_factory()() as session:
                artifact = session.get(Artifact, run.parameters["canonical_audio_id"])
                if not artifact or artifact.trashed_at is not None:
                    raise ValueError("Canonical audio is unavailable")
                sound = {
                    "relative_path": artifact.relative_path,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                    "samples": run.parameters["audio_samples"],
                    "sample_rate": run.parameters["audio_rate"],
                }
        return runner.request(
            "POST",
            "/v1/runs/media-compose",
            {
                "run_id": run.id,
                **self.native_budget(run),
                **({"audio": sound} if sound else {}),
                "permissions": run.effective_permissions,
                "clips": clips,
                "fps": run.parameters["timeline"]["fps"],
                "target_frames": run.parameters["timeline"]["target_frames"],
                "width": run.parameters["width"],
                "height": run.parameters["height"],
            },
        )

    def output_metadata(self, output):
        report = json.loads(safe_join(get_settings().data_dir, output).with_suffix(".json").read_text())
        if report.get("verified") is not True:
            raise ValueError("Composition was not fully verified")
        return report

    def on_success(self, session, run, artifact):
        task = run.task
        plan = task.metadata_json["media_plan"]
        if run.id != plan["compose_run_id"]:
            raise ValueError("Stale composition revision")
        sources = {
            a.run_id: a.id
            for a in session.scalars(
                select(Artifact).where(
                    Artifact.run_id.in_(run.parameters["stage_run_ids"]), Artifact.artifact_type == "video"
                )
            )
        }
        artifact.parent_artifact_ids = [sources[rid] for rid in run.parameters["stage_run_ids"]]
        if run.parameters.get("canonical_audio_id"):
            artifact.parent_artifact_ids = [
                *artifact.parent_artifact_ids,
                run.parameters["canonical_audio_id"],
            ]
        artifact.metadata_json = {
            **artifact.metadata_json,
            "media_job_id": task.id,
            "revision": plan["revision"],
            "composition_mode": plan["mode"],
            "backend": run.parameters["backend"],
        }
        task.metadata_json = {**task.metadata_json, "media_plan": {**plan, "final_artifact_id": artifact.id}}
        task.updated_at = utcnow()


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    expected_revision: StrictInt = Field(ge=1, le=20)


@router.post("/{task_id}/resume", status_code=202)
def resume(task_id: UUID, body: ResumeRequest, session: DB):
    from app.runner_client import RunnerClient

    task = job(session, task_id)
    lock_task(session, task)
    receipts = task.metadata_json.get("media_receipts", {})
    key = str(body.client_request_id)
    if key in receipts:
        saved = receipts[key]
        if saved["expected_revision"] != body.expected_revision:
            raise HTTPException(409, "Resume ID belongs to another request")
        return saved["response"]
    plan = task.metadata_json["media_plan"]
    view = job_view(session, task)
    if plan["revision"] != body.expected_revision:
        raise HTTPException(409, "Media plan changed; refresh before resuming")
    if not view["resume_allowed"] or plan["revision"] >= 20:
        raise HTTPException(409, "Inspect active/completed work before resuming")
    observed = capabilities().get("profile_observation") if plan["kind"] == "video" else None
    if plan.get("profile_observation") and observed != plan["profile_observation"]:
        raise HTTPException(409, "Runtime model files changed; start a new media job")
    selected_ids = (
        [plan["speech_run_id"], plan["planner_run_id"]]
        if plan.get("timing") is None
        else [*plan["segment_run_ids"], plan["compose_run_id"]]
    )
    selected = [session.get(Run, rid) for rid in selected_ids]
    for run in selected:
        if (
            run.status != "succeeded"
            and run.metadata_json.get("dispatch_attempted")
            and not run.metadata_json.get("process_confirmed_gone")
        ):
            inspected = RunnerClient().inspect_process(run.id)
            if inspected.get("alive", True) or inspected.get("completion_pending"):
                raise HTTPException(409, "An owned process still requires inspection")
    next_revision = plan["revision"] + 1
    task.metadata_json = {
        key: value for key, value in task.metadata_json.items() if key != "stop_requested_at"
    }
    if plan.get("timing") is None:
        speech, old_planner = selected
        audio = session.scalar(
            select(Artifact).where(
                Artifact.run_id == speech.id, Artifact.artifact_type == "audio", Artifact.trashed_at.is_(None)
            )
        )
        if speech.status != "succeeded" or audio is None:
            speech = create_run(
                session,
                task,
                run_type=speech.run_type,
                capability=speech.capability,
                executor_type=speech.executor_type,
                execution_target=speech.execution_target,
                parameters=dict(speech.parameters),
                permissions=list(speech.effective_permissions),
                requested_gpu=speech.requested_gpu,
                requested_resources=dict(speech.requested_resources),
                operation_key=f"media:{next_revision}:speech:attempt:1",
                parent_run_id=speech.id,
                retry_class="inspect",
            )
        planner = create_run(
            session,
            task,
            run_type=old_planner.run_type,
            capability=old_planner.capability,
            executor_type=old_planner.executor_type,
            execution_target=old_planner.execution_target,
            parameters={**old_planner.parameters, "speech_run_id": speech.id},
            permissions=list(old_planner.effective_permissions),
            operation_key=f"media:{next_revision}:plan:attempt:1",
            parent_run_id=old_planner.id,
            retry_class="inspect",
        )
        depend_on(session, planner, speech)
        updated = {
            **plan,
            "revision": next_revision,
            "speech_run_id": speech.id,
            "planner_run_id": planner.id,
        }
        return save_resume(session, task, plan, updated, receipts, key, body)
    new_ids = []
    previous = None
    reusable_prefix = True
    for index, rid in enumerate(plan["segment_run_ids"]):
        source = session.get(Run, rid)
        artifact = session.scalar(
            select(Artifact).where(Artifact.run_id == rid, Artifact.artifact_type == "video")
        )
        reusable = (
            source.status == "succeeded"
            and artifact
            and artifact.trashed_at is None
            and safe_join(get_settings().data_dir, artifact.relative_path).is_file()
        )
        if reusable and (plan["mode"] != "continuous" or reusable_prefix):
            run = source
        else:
            reusable_prefix = False
            run = create_run(
                session,
                task,
                run_type=source.run_type,
                capability=source.capability,
                executor_type=source.executor_type,
                execution_target=source.execution_target,
                operation_key=f"media:{next_revision}:segment:{index}:attempt:1",
                parameters=dict(source.parameters),
                permissions=list(source.effective_permissions),
                requested_gpu=source.requested_gpu,
                requested_resources=dict(source.requested_resources),
                parent_run_id=source.id,
                retry_class="inspect",
            )
            if previous and plan["mode"] == "continuous":
                run.parameters = {**run.parameters, "previous_video_run_id": previous.id}
                depend_on(session, run, previous)
        new_ids.append(run.id)
        previous = run
    old_compose = session.get(Run, plan["compose_run_id"])
    compose = create_run(
        session,
        task,
        run_type="video",
        capability="media.compose",
        executor_type="media_compose",
        execution_target="host",
        operation_key=f"media:{next_revision}:compose:attempt:1",
        parameters={**old_compose.parameters, "stage_run_ids": new_ids},
        permissions=list(old_compose.effective_permissions),
        parent_run_id=old_compose.id,
        retry_class="inspect",
    )
    for rid in new_ids:
        depend_on(session, compose, session.get(Run, rid))
    updated = {
        **plan,
        "revision": next_revision,
        "segment_run_ids": new_ids,
        "compose_run_id": compose.id,
        "final_artifact_id": None,
    }
    return save_resume(session, task, plan, updated, receipts, key, body)


def save_resume(session, task, plan, updated, receipts, key, body):
    task.metadata_json = {
        **task.metadata_json,
        "media_revisions": [*task.metadata_json.get("media_revisions", []), plan],
        "media_plan": updated,
        RESOURCE_WAIT_KEY: None,
    }
    result = job_view(session, task)
    task.metadata_json = {
        **task.metadata_json,
        "media_receipts": {
            **receipts,
            key: {"expected_revision": body.expected_revision, "response": result},
        },
    }
    task.updated_at = utcnow()
    session.commit()
    return result


class FullAvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_request_id: UUID
    speech_text: str | None = Field(default=None, min_length=1, max_length=1000)
    image_artifact_id: UUID
    audio_artifact_id: UUID
    prompt: str = Field(default="A person speaking naturally, static camera.", min_length=1, max_length=2000)
    size: Literal[256, 384, 512] = 384
    steps: StrictInt = Field(default=8, ge=4, le=30)
    seed: StrictInt = Field(default=43, ge=0, le=2147483647)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")


def publish_avatar(session, body, *, task=None, parent_run_id=None):
    import wave

    from app.avatars import AvatarRequest, create_avatar_run
    from app.media_plan import audio_frames

    existing = session.get(Task, str(body.client_request_id)) if task is None else None
    request = (
        task.metadata_json.get("media_request", body.model_dump(mode="json"))
        if task
        else body.model_dump(mode="json")
    )
    if existing:
        if existing.metadata_json.get("media_plan", {}).get("request") != request:
            raise HTTPException(409, "Request ID belongs to another media intent")
        return job_view(session, existing)
    image = session.get(Artifact, str(body.image_artifact_id))
    if not image or image.trashed_at is not None or image.mime_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(422, "Choose an available PNG/JPEG portrait")
    if body.speech_text is not None:
        from app.audio import SpeechRequest, create_audio_run

        if task is None:
            task = Task(
                id=str(body.client_request_id),
                title=body.prompt[:80],
                prompt=body.prompt,
                capability="avatar.long",
                metadata_json={"media_request": request},
            )
            session.add(task)
            session.flush()
        lock_task(session, task)
        task.metadata_json = {**task.metadata_json, "media_request": request}
        speech = create_audio_run(
            session,
            SpeechRequest(text=body.speech_text, reference_artifact_id=body.audio_artifact_id, gpu=body.gpu),
            task=task,
            parent_run_id=parent_run_id,
        )
        speech.parameters = {**speech.parameters, "full_avatar_after_speech": request}
        planner = create_run(
            session,
            task,
            run_type="video",
            capability="avatar.plan",
            executor_type="avatar_media_plan",
            execution_target="container",
            operation_key="media:1:plan:attempt:1",
            parent_run_id=parent_run_id,
            parameters={"speech_run_id": speech.id, "request": request},
            permissions=["filesystem_read", "workspace_write"],
            retry_class="inspect",
        )
        depend_on(session, planner, speech)
        task.metadata_json = {
            **task.metadata_json,
            "media_plan": {
                "version": 1,
                "revision": 1,
                "kind": "avatar",
                "mode": "continuous",
                "timing": None,
                "segment_run_ids": [],
                "compose_run_id": None,
                "speech_run_id": speech.id,
                "planner_run_id": planner.id,
                "request": request,
                "final_artifact_id": None,
            },
        }
        return job_view(session, task)
    audio = session.get(Artifact, str(body.audio_artifact_id))
    image = session.get(Artifact, str(body.image_artifact_id))
    if (
        not audio
        or audio.artifact_type != "audio"
        or audio.mime_type != "audio/wav"
        or audio.trashed_at is not None
        or not image
        or image.artifact_type != "image"
        or image.trashed_at is not None
    ):
        raise HTTPException(422, "Choose available portrait and canonical WAV artifacts")
    try:
        with wave.open(str(safe_join(get_settings().data_dir, audio.relative_path)), "rb") as wav:
            samples, rate = wav.getnframes(), wav.getframerate()
            if (
                not 8000 <= rate <= 96000
                or wav.getnchannels() not in {1, 2}
                or wav.getsampwidth() not in {1, 2, 3, 4}
                or not 0.68 <= samples / rate <= 60
            ):
                raise ValueError("Unsupported canonical WAV")
    except (OSError, ValueError, EOFError, wave.Error) as exc:
        raise HTTPException(422, "Choose an intact PCM WAV of 0.68–60 seconds") from exc
    timing = timeline(frames=audio_frames(samples, rate), fps=25, seed=body.seed, mode="continuous")
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
    revision = task.metadata_json.get("media_plan", {}).get("revision", 1)
    runs = []
    previous = None
    for segment in timing.segments:
        settings = AvatarRequest(
            image_artifact_id=body.image_artifact_id,
            audio_artifact_id=body.audio_artifact_id,
            prompt=body.prompt,
            size=body.size,
            steps=body.steps,
            seed=segment.seed,
            gpu=body.gpu,
            frames=segment.generated_frames,
        )
        run = create_avatar_run(session, settings, task=task, parent_run_id=parent_run_id)
        run.operation_key = f"media:{revision}:segment:{segment.index}:attempt:1"
        run.requested_resources = {"ram_mib": 16384}
        run.parameters = {
            **run.parameters,
            "internal_media": True,
            "media_segment": segment.model_dump(),
            "audio_window": {"start_frame": segment.start_frame - segment.first_frame},
        }
        if previous:
            run.parameters = {**run.parameters, "previous_video_run_id": previous.id}
            depend_on(session, run, previous)
        runs.append(run)
        previous = run
    compose = create_run(
        session,
        task,
        run_type="video",
        capability="media.compose",
        executor_type="media_compose",
        execution_target="host",
        operation_key=f"media:{revision}:compose:attempt:1",
        parameters={
            "stage_run_ids": [r.id for r in runs],
            "timeline": timing.model_dump(mode="json"),
            "width": body.size,
            "height": body.size,
            "backend": "echomimic-v3",
            "composition_mode": "continuous",
            "canonical_audio_id": audio.id,
            "audio_samples": samples,
            "audio_rate": rate,
        },
        permissions=["filesystem_read", "workspace_write"],
        retry_class="inspect",
    )
    for run in runs:
        depend_on(session, compose, run)
    task.metadata_json = {
        **task.metadata_json,
        "media_plan": {
            "version": 1,
            "revision": revision,
            "kind": "avatar",
            "mode": "continuous",
            "timing": timing.model_dump(mode="json"),
            "segment_run_ids": [r.id for r in runs],
            "compose_run_id": compose.id,
            "request": request,
            "final_artifact_id": None,
            "canonical_audio_id": audio.id,
        },
    }
    session.flush()
    return job_view(session, task)


@router.post("/avatar", status_code=202)
def avatar(body: FullAvatarRequest, session: DB):
    result = publish_avatar(session, body)
    session.commit()
    return result


class AvatarPlannerExecutor:
    name = "avatar_media_plan"

    def execute(self, session, run):
        from app.permissions import require
        from app.runs import transition
        from app.state import RunStatus

        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        audio = session.scalar(
            select(Artifact).where(
                Artifact.run_id == run.parameters["speech_run_id"], Artifact.artifact_type == "audio"
            )
        )
        if not audio or audio.trashed_at is not None:
            raise ValueError("Completed canonical speech is unavailable")
        request = FullAvatarRequest.model_validate(
            {**run.parameters["request"], "audio_artifact_id": audio.id, "speech_text": None}
        )
        publish_avatar(session, request, task=run.task, parent_run_id=run.id)
        transition(session, run, RunStatus.RUNNING, event_type="executor.started", payload={})
        transition(
            session,
            run,
            RunStatus.SUCCEEDED,
            event_type="media.plan_prepared",
            payload={"task_id": run.task_id},
        )
        return "done"
