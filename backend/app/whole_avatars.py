"""One source-bound avatar Run; whole-plan publication lives in media_jobs.

No Runner imports: the control plane uses only portable observations and the
typed private transport. Normal tests use temporary files and fake processes.
"""

import hashlib
import io
import json
import math
import wave
from datetime import timedelta
from typing import Literal

from fastapi import HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact
from app.paths import safe_join
from app.python_execution import read_owned_file
from app.resources import ResourceUnknown, reserve_gpu_bundle
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run

PROFILE = "sonic_whole_768_v1"
RAM_MIB = 18432
MAX_SECONDS = 14400


class WholeRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Literal["sonic_whole_768_v1"]
    observation: str = Field(pattern=r"^[a-f0-9]{64}$")


def capabilities():
    try:
        return RunnerClient().request("GET", "/v1/avatar/whole-capabilities")
    except (RunnerError, RunnerUnavailable):
        return {"available": False, "reason": "The whole-recording avatar Runner is unavailable"}


def frozen_recipe(value):
    return WholeRecipe.model_validate(value).model_dump()


def verify_recipe(profile, value):
    try:
        recipe = frozen_recipe(value)
    except ValueError as exc:
        raise HTTPException(409, "Refresh whole-recording avatar setup before starting") from exc
    if (
        profile.get("available") is not True
        or profile.get("backend") != "sonic"
        or profile.get("recipe") != recipe
        or profile.get("ram_mib") != RAM_MIB
        or profile.get("max_side") != 768
        or profile.get("max_pixels") != 512 * 768
        or profile.get("fps") != 25
    ):
        raise HTTPException(
            409, "Whole-recording avatar setup changed or is unavailable; refresh before starting"
        )
    return recipe


def canvas(width, height):
    if (
        type(width) is not int
        or type(height) is not int
        or not 32 <= min(width, height) <= max(width, height) <= 8192
        or max(width, height) > min(width, height) * 4
    ):
        raise ValueError("Choose a bounded portrait with aspect ratio at most 4:1")
    longest = max(width, height)
    for bound in range(768, 191, -64):
        result = tuple(((side * bound + longest * 64 - 1) // (longest * 64)) * 64 for side in (width, height))
        if result[0] * result[1] <= 512 * 768:
            return result
    raise ValueError("Portrait does not fit the bounded whole-recording canvas")


def source_snapshot(artifact):
    return {
        "artifact_id": artifact.id,
        "relative_path": artifact.relative_path,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
    }


def inspect_sources(session, portrait_id, audio_id, *, reference=False):
    portrait, audio = session.get(Artifact, str(portrait_id)), session.get(Artifact, str(audio_id))
    if (
        portrait is None
        or portrait.trashed_at is not None
        or portrait.artifact_type != "image"
        or portrait.mime_type not in {"image/png", "image/jpeg"}
        or audio is None
        or audio.trashed_at is not None
        or audio.artifact_type != "audio"
        or audio.mime_type != "audio/wav"
    ):
        raise ValueError("Choose an available portrait and canonical PCM recording")
    raw = []
    for artifact in (portrait, audio):
        raw.append(
            read_owned_file(
                artifact.relative_path, artifact.size_bytes, artifact.sha256, limit=20 * 1024**2, binary=True
            )
        )
    with Image.open(io.BytesIO(raw[0])) as image:
        if image.format not in {"PNG", "JPEG"}:
            raise ValueError("Choose an intact PNG/JPEG portrait")
        canvas(*image.size)  # Bound decoding before loading pixels/EXIF transpose.
        image.verify()
    with Image.open(io.BytesIO(raw[0])) as image:
        width, height = canvas(*ImageOps.exif_transpose(image).size)
    with wave.open(io.BytesIO(raw[1]), "rb") as source:
        samples, rate, channels, sample_width = (
            source.getnframes(),
            source.getframerate(),
            source.getnchannels(),
            source.getsampwidth(),
        )
        if (
            not 8000 <= rate <= 96000
            or channels not in {1, 2}
            or sample_width not in {1, 2, 3, 4}
            or samples * 100 < rate * (10 if reference else 68)
            or samples > rate * 60
            or source.getcomptype() != "NONE"
            or len(source.readframes(samples)) != samples * channels * sample_width
        ):
            raise ValueError("Choose intact canonical PCM WAV speech of 0.68–60 seconds")
    frames = (samples * 25 + rate - 1) // rate
    base = (frames + 1) // 2
    return [source_snapshot(portrait), source_snapshot(audio)], {
        "width": width,
        "height": height,
        "samples": samples,
        "sample_rate": rate,
        "channels": channels,
        "sample_width": sample_width,
        "target_frames": frames,
        "base_frames": base,
        "endpoint_frames": frames - (2 * base - 1),
    }


def verify_snapshots(session, snapshots):
    if not isinstance(snapshots, list) or len(snapshots) != 2:
        raise ValueError("Missing frozen whole-recording sources")
    for item in snapshots:
        artifact = session.get(Artifact, item["artifact_id"])
        if artifact is None or artifact.trashed_at is not None or source_snapshot(artifact) != item:
            raise ValueError("Whole-recording sources changed after review")
        read_owned_file(artifact.relative_path, artifact.size_bytes, artifact.sha256, limit=20 * 1024**2)


def create_whole_run(
    session, body, *, task, parent_run_id=None, recipe=None, observed_profile=None, execution_deadline_at=None
):
    from app.media_jobs import execution_budget

    if body.generation_profile != PROFILE:
        raise ValueError("Whole-recording execution requires its explicitly selected quality profile")
    profile = capabilities() if observed_profile is None else observed_profile
    selected = verify_recipe(profile, recipe if recipe is not None else profile.get("recipe"))
    inputs, observation = inspect_sources(session, body.image_artifact_id, body.audio_artifact_id)
    deadline = execution_deadline_at or (utcnow() + timedelta(seconds=MAX_SECONDS)).isoformat()
    execution_budget(deadline)
    count = 2 if body.gpu == "auto" and profile.get("detected_gpu_count", 1) >= 2 else 1
    return create_run(
        session,
        task,
        run_type="video",
        capability="avatar.animate",
        executor_type="sonic_whole",
        execution_target="host",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        requested_resources={"ram_mib": RAM_MIB, "gpu_count": count},
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            "generation_profile": PROFILE,
            "whole_recipe": selected,
            "whole_inputs": inputs,
            "observed_input": observation,
            "seed": body.seed,
            "gpu_count": count,
            "steps": 25,
            "max_side": 768,
            "backend": "sonic",
            "execution_deadline_at": deadline,
            "parent_artifact_ids": [item["artifact_id"] for item in inputs],
        },
    )


class WholeAvatarExecutor(HostMediaExecutor):
    name = "sonic_whole"
    suffix, artifact_type, mime_type = ".mp4", "video", "video/mp4"

    def on_inspection(self, session, run, info):
        try:
            path = safe_join(get_settings().data_dir, f"runs/{run.id}/whole-avatar/progress.json")
            if path.resolve() != path or path.stat().st_size > 4096:
                return
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        fields = {"version", "run_id", "recipe", "phase", "completed_windows", "total_windows"}
        total = ((run.parameters["observed_input"]["base_frames"] + 24) // 25) * 25
        phases = {"preparing": 0, "animating": 1, "finishing": 2}
        if (
            type(value) is not dict
            or set(value) != fields
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["run_id"] != run.id
            or value["recipe"] != run.parameters["whole_recipe"]
            or type(value["phase"]) is not str
            or value["phase"] not in phases
            or type(value["completed_windows"]) is not int
            or type(value["total_windows"]) is not int
            or value["total_windows"] != total
            or not 0 <= value["completed_windows"] <= total
            or value["phase"] == "preparing"
            and value["completed_windows"] != 0
            or value["phase"] == "finishing"
            and value["completed_windows"] != total
        ):
            return
        current = {key: value[key] for key in ("phase", "completed_windows", "total_windows")}
        previous = run.metadata_json.get("avatar_progress")
        if previous and (
            phases[current["phase"]] < phases[previous["phase"]]
            or current["completed_windows"] < previous["completed_windows"]
        ):
            return
        if current != previous:
            run.metadata_json = {**run.metadata_json, "avatar_progress": current}
            append_event(session, run.id, "avatar.progress", current)

    def reserve_devices_from_hardware(self, session, run, hardware):
        count = run.parameters["gpu_count"]
        if type(count) is not int or count not in {1, 2}:
            raise ValueError("Invalid whole-recording GPU allocation policy")
        values = {}
        for gpu in hardware.get("gpus", []):
            total, used = gpu.get("memory_total_mib"), gpu.get("memory_used_mib")
            if all(
                type(value) in {int, float} and math.isfinite(value) and value >= 0 for value in (total, used)
            ):
                values[int(gpu["index"])] = max(0, total - used)
        requested = run.requested_gpu
        all_ids = {int(gpu["index"]) for gpu in hardware.get("gpus", [])}
        if requested != "auto" and (not requested.isdigit() or int(requested) not in all_ids):
            raise ResourceUnknown("Requested avatar GPU is not present")
        primary_minimum = 10800 if count == 2 else 7168
        primaries = [
            index
            for index, free in sorted(values.items(), key=lambda row: row[1], reverse=True)
            if free >= primary_minimum
        ]
        if requested != "auto":
            primaries = [index for index in primaries if index == int(requested)]
        for primary in primaries:
            auxiliary = [
                index
                for index, free in sorted(values.items(), key=lambda row: row[1], reverse=True)
                if index != primary and free >= 6500
            ]
            if count == 2 and not auxiliary:
                continue
            selections = [[primary, secondary] for secondary in auxiliary] if count == 2 else [[primary]]
            for selected in selections:
                # A busy primary cannot promote a lower-VRAM auxiliary into
                # that role: each atomic attempt contains exactly one pair.
                result = reserve_gpu_bundle(session, run, selected, count)
                if result is not None:
                    return result
        return None  # Wait for actual free VRAM; never stop an external runtime.

    def validate_inputs(self, session, run):
        sources = run.parameters["whole_inputs"]
        if not isinstance(sources, list) or len(sources) != 2:
            raise ValueError("Missing frozen whole-recording inputs")
        inputs, observation = inspect_sources(session, sources[0]["artifact_id"], sources[1]["artifact_id"])
        if inputs != sources or observation != run.parameters["observed_input"]:
            raise ValueError("Whole-recording sources changed after publication")
        frozen_recipe(run.parameters["whole_recipe"])
        if run.parameters.get("media_inputs"):
            from app.agent_media import verify_published_inputs

            verify_published_inputs(session, run)

    def _start(self, runner, run, allocated, output):
        sources = run.parameters["whole_inputs"]
        return runner.request(
            "POST",
            "/v1/runs/whole-avatar",
            {
                "run_id": run.id,
                "recipe": frozen_recipe(run.parameters["whole_recipe"]),
                "portrait": {key: sources[0][key] for key in ("relative_path", "size_bytes", "sha256")},
                "audio": {key: sources[1][key] for key in ("relative_path", "size_bytes", "sha256")},
                "observed_input": run.parameters["observed_input"],
                "seed": run.parameters["seed"],
                "gpus": [int(value) for value in run.allocated_resources["gpus"]],
                "permissions": run.effective_permissions,
                **self.native_budget(run),
            },
        )

    def on_success(self, session, run, artifact):
        report = artifact.metadata_json["avatar_verification"]
        if (
            report["recipe"] != run.parameters["whole_recipe"]
            or report["observed_input"] != run.parameters["observed_input"]
            or any(type(value) is not int for value in report["observed_input"].values())
            or report["input_sha256"]
            != dict(
                zip(
                    ("portrait", "audio"),
                    (item["sha256"] for item in run.parameters["whole_inputs"]),
                    strict=True,
                )
            )
        ):
            raise ValueError("Native whole-recording verification does not match its frozen sources")
        plan = run.task.metadata_json.get("media_plan", {})
        if plan.get("version") != 2 or plan.get("whole_run_id") != run.id:
            raise ValueError("Whole-recording output belongs to a stale media plan")
        artifact.metadata_json = {
            **{key: value for key, value in artifact.metadata_json.items() if key != "internal_media"},
            "media_job_id": run.task_id,
            "revision": plan["revision"],
            "composition_mode": "whole_recording",
            "width": run.parameters["observed_input"]["width"],
            "height": run.parameters["observed_input"]["height"],
            "fps": 25,
            "frames": run.parameters["observed_input"]["target_frames"],
        }
        run.task.metadata_json = {
            **run.task.metadata_json,
            "media_plan": {**plan, "final_artifact_id": artifact.id},
        }
        run.task.updated_at = utcnow()

    def output_metadata(self, output):
        path = safe_join(get_settings().data_dir, output)
        report_path = path.with_suffix(".json")
        if report_path.resolve() != report_path or report_path.stat().st_size > 16384:
            raise ValueError("Invalid whole-recording verification path or size")
        report = json.loads(report_path.read_text())
        fields = {
            "version",
            "verified",
            "run_id",
            "backend",
            "recipe",
            "observed_input",
            "input_sha256",
            "video_sha256",
        }
        if (
            type(report) is not dict
            or set(report) != fields
            or type(report["version"]) is not int
            or report["version"] != 1
            or report["verified"] is not True
            or report["run_id"] != path.stem
            or report["backend"] != "sonic"
        ):
            raise ValueError("Missing successful native whole-recording verification")
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != report["video_sha256"]:
                raise ValueError("Verified whole-recording movie bytes changed")
        return {"verified": True, "avatar_verification": report}
