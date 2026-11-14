"""Recurrent video adapter over the common owned-process lifecycle.

The shared worker registers this adapter; native admission stays closed until
managed-runtime inference and temporal qualification pass.
"""

import math
import re
import time

from sqlalchemy import select

from app.events import append_event
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact, Run
from app.motion_artifacts import MotionArtifacts

NAME = "wan_svi_video"
PROFILE = "wan22-svi-pro-q4-linux-x86-64-python312-v1"
RAM_MIB = 18432
GEOMETRY = {"width": 832, "height": 480, "frames": 81, "fps": 15, "steps": 20, "cfg": 5}


def geometry(values=None):
    values = GEOMETRY if values is None else values
    width, height = values.get("width"), values.get("height")
    if type(width) is not int or type(height) is not int or (width, height) not in {(832, 480), (480, 832)}:
        raise ValueError("Choose the fixed landscape or portrait SVI geometry")
    return {**GEOMETRY, "width": width, "height": height}


def generation_profile(values):
    selected = geometry(values)
    return "portrait" if selected["height"] > selected["width"] else "landscape"


def descriptor(artifact):
    return {key: getattr(artifact, key) for key in ("relative_path", "sha256", "size_bytes")}


def available_artifact(row, owner):
    return bool(
        row is not None
        and row.owner_id == owner
        and row.trashed_at is None
        and row.purged_at is None
        and row.purge_run_id is None
    )


def checked_parameters(run):
    if not isinstance(run.requested_gpu, str) or not re.fullmatch(r"auto|[0-9]{1,12}", run.requested_gpu):
        raise ValueError("SVI needs an explicit compatible GPU choice or auto")
    return checked_recipe(run.parameters, run.requested_resources)


def checked_recipe(values, resources):
    selected = geometry(values)
    runtime = values.get("managed_runtime")
    eligible = values.get("managed_video_gpu_indices")
    if (
        type(resources.get("ram_mib")) is not int
        or resources.get("ram_mib") != RAM_MIB
        or any(values.get(key) != expected for key, expected in selected.items())
        or not isinstance(runtime, dict)
        or set(runtime) != {"profile", "manifest_sha256", "environment_id"}
        or runtime["profile"] != PROFILE
        or any(
            not isinstance(runtime[key], str) or not re.fullmatch(r"[a-f0-9]{64}", runtime[key])
            for key in ("manifest_sha256", "environment_id")
        )
        or not isinstance(eligible, list)
        or not eligible
        or any(type(index) is not int or index < 0 for index in eligible)
    ):
        raise ValueError("SVI needs its frozen engine, geometry and full resource reservation")
    return values


class SviExecutor(MotionArtifacts, HostMediaExecutor):
    name = NAME
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"
    motion_role = "svi_motion"
    motion_filename = "svi-motion.safetensors"
    motion_context_frames = 4

    @staticmethod
    def native_budget(run):
        budget = HostMediaExecutor.native_budget(run)
        if "deadline_at" not in budget:
            raise ValueError("SVI needs its frozen workflow deadline")
        return {"deadline_at": min(budget["deadline_at"], time.time() + 3600)}

    def reserve_devices_from_hardware(self, session, run, hardware):
        values = checked_parameters(run)
        selected = {
            **hardware,
            "gpus": [
                row
                for row in hardware.get("gpus", [])
                if int(row["index"]) in values["managed_video_gpu_indices"]
                and type(row.get("memory_total_mib")) in {int, float}
                and math.isfinite(row["memory_total_mib"])
                and row["memory_total_mib"] >= 12288
            ],
        }
        return super().reserve_devices_from_hardware(session, run, selected)

    def validate_inputs(self, session, run):
        values = checked_parameters(run)
        from app.media_translation import validate_media_translation

        validate_media_translation(session, run)
        if values.get("media_inputs"):
            from app.agent_media import verify_published_inputs

            verify_published_inputs(session, run)
        source = session.get(Artifact, values.get("image_artifact_id", ""))
        if (
            not available_artifact(source, run.owner_id)
            or source.artifact_type != "image"
            or source.mime_type not in {"image/png", "image/jpeg"}
            or descriptor(source) != values.get("image")
            or source.id not in values.get("parent_artifact_ids", [])
        ):
            raise ValueError("The frozen SVI original image is unavailable or changed")
        previous_id = values.get("previous_motion_run_id")
        if not previous_id:
            if values.get("previous_motion") is not None:
                raise ValueError("SVI motion must come from its owned completed producer")
            return
        previous = session.get(Run, previous_id)
        if (
            previous is None
            or previous.owner_id != run.owner_id
            or previous.executor_type != self.name
            or previous.status != "succeeded"
            or previous.parameters.get("image") != values["image"]
            or previous.parameters.get("managed_runtime") != values["managed_runtime"]
            or any(previous.parameters.get(key) != values.get(key) for key in ("width", "height", "fps"))
        ):
            raise ValueError("SVI continuation needs the same owned anchor and completed engine")
        video = session.scalar(
            select(Artifact).where(Artifact.run_id == previous.id, Artifact.artifact_type == "video")
        )
        if not available_artifact(video, run.owner_id):
            raise ValueError("The preceding SVI video is unavailable")
        profile = video.metadata_json.get("profile_identity")
        if (
            not isinstance(profile, str)
            or not re.fullmatch(r"[a-f0-9]{64}", profile)
            or video.metadata_json.get("managed_runtime") != values["managed_runtime"]
        ):
            raise ValueError("The preceding SVI video profile changed")
        motion = session.get(Artifact, video.metadata_json.get("motion_context_artifact_id", ""))
        if (
            not available_artifact(motion, run.owner_id)
            or motion.run_id != previous.id
            or motion.artifact_type != "document"
            or motion.metadata_json.get("role") != self.motion_role
            or motion.metadata_json.get("context_frames") != 4
            or motion.metadata_json.get("profile_identity") != profile
            or type(motion.size_bytes) is not int
            or not 0 < motion.size_bytes <= 512 * 1024
            or video.id not in motion.parent_artifact_ids
        ):
            raise ValueError("The owned SVI motion provenance or profile changed")
        snapshot = descriptor(motion)
        if values.get("previous_motion") not in (None, snapshot) or values.get(
            "svi_profile_identity"
        ) not in (None, profile):
            raise ValueError("The frozen SVI motion snapshot changed")
        if values.get("previous_motion") == snapshot:
            if (
                values.get("previous_motion_artifact_id") != motion.id
                or values.get("svi_profile_identity") != profile
                or motion.id not in values["parent_artifact_ids"]
            ):
                raise ValueError("The frozen SVI motion lineage changed")
            return
        run.parameters = {
            **values,
            "previous_motion": snapshot,
            "previous_motion_artifact_id": motion.id,
            "svi_profile_identity": profile,
            "parent_artifact_ids": list(dict.fromkeys([*values["parent_artifact_ids"], motion.id])),
        }
        append_event(
            session,
            run.id,
            "motion.context.bound",
            {"source_run_id": previous.id, "artifact_id": motion.id, "profile_identity": profile},
        )

    def _start(self, runner, run, allocated, output):
        values = checked_parameters(run)
        return runner.request(
            "POST",
            "/v1/runs/svi",
            {
                "run_id": run.id,
                **self.native_budget(run),
                "managed_runtime": values["managed_runtime"],
                "image": values["image"],
                "previous_motion": values.get("previous_motion"),
                "prompt": values["prompt"],
                "negative_prompt": values.get("negative_prompt", ""),
                "seed": values["seed"],
                "gpu": int(allocated),
                "permissions": run.effective_permissions,
                **({"generation_profile": "portrait"} if generation_profile(values) == "portrait" else {}),
            },
        )

    def on_success(self, session, run, artifact):
        metadata = artifact.metadata_json
        profile = metadata.get("profile_identity")
        motion_info = metadata.get("motion_context")
        expected_motion = f"artifacts/{run.id[:2]}/{run.id[2:4]}/{run.id}.safetensors"
        if (
            not isinstance(profile, str)
            or not re.fullmatch(r"[a-f0-9]{64}", profile)
            or any(metadata.get(key) != expected for key, expected in geometry(run.parameters).items())
            or metadata.get("managed_runtime") != run.parameters["managed_runtime"]
            or metadata.get("backend") != "wan22-svi-pro-q4"
            or metadata.get("output_sha256") != artifact.sha256
            or run.parameters.get("svi_profile_identity") not in (None, profile)
            or not isinstance(motion_info, dict)
            or motion_info.get("relative_path") != expected_motion
        ):
            raise ValueError("The SVI output differs from its frozen production recipe")
        super().on_success(session, run, artifact)
        motion = session.get(Artifact, artifact.metadata_json["motion_context_artifact_id"])
        motion.metadata_json = {**motion.metadata_json, "profile_identity": profile}
