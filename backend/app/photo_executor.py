"""Adapter around the existing photo pipeline's typed Runner operation."""

import json
from pathlib import Path

from app.config import get_settings
from app.events import append_event
from app.host_media_executor import HostMediaExecutor
from app.paths import safe_join
from app.permissions import require


class PhotoPipeExecutor(HostMediaExecutor):
    name = "photo_pipe"
    suffix = ".png"
    artifact_type = "image"
    mime_type = "image/png"

    def validate_inputs(self, session, run):
        from app.media_translation import validate_media_translation

        validate_media_translation(session, run)

    def output_metadata(self, output):
        relative = str(Path(output).with_suffix(".json"))
        root = get_settings().data_dir.resolve()
        sidecar = safe_join(root, relative)
        if sidecar != root / relative:
            raise ValueError("Image execution receipt must not contain symlinks")
        if not sidecar.exists():
            return {}
        if sidecar.stat().st_size > 16 * 1024:
            raise ValueError("Image execution receipt exceeds its limit")
        report = json.loads(sidecar.read_text())
        if "fully_resident_cuda_weights_checked" not in report:
            return {}
        if (
            report.get("fully_resident_cuda_weights_checked") is not True
            or report.get("cpu_offload") is not False
        ):
            raise ValueError("Krea did not verify GPU-only inference")
        return {"execution": report}

    def reserve_devices(self, session, run, indexes):
        if run.parameters.get("backend") == "krea2":
            from app.resources import reserve_gpu_bundle

            return reserve_gpu_bundle(session, run, indexes, run.requested_resources["gpu_count"])
        return super().reserve_devices(session, run, indexes)

    def on_success(self, session, run, artifact):
        if run.metadata_json.get("prompt_translation"):
            artifact.metadata_json = {
                **artifact.metadata_json,
                "prompt_translation": run.metadata_json["prompt_translation"],
            }
            receipt_id = run.metadata_json["prompt_translation"].get("artifact_id")
            if receipt_id and receipt_id not in artifact.parent_artifact_ids:
                artifact.parent_artifact_ids = [*artifact.parent_artifact_ids, receipt_id]
        if run.parameters.get("video_prompt"):
            self.queue_video(session, run, artifact)
            return
        if not run.parameters.get("upscale_result"):
            return
        from app.images import ImageRequest, create_image_run

        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        if run.parameters.get("mode") == "upscale" or run.metadata_json.get("upscale_run_id"):
            raise ValueError("Invalid repeated image workflow dispatch")
        child = create_image_run(
            session,
            ImageRequest(mode="upscale", input_artifact_ids=[artifact.id], gpu=run.requested_gpu),
            task=run.task,
            parent_run_id=run.id,
        )
        child.effective_permissions = list(run.effective_permissions)
        child.triggered_by = run.triggered_by
        if run.parameters.get("execution_deadline_at"):
            child.parameters = {
                **child.parameters,
                "execution_deadline_at": run.parameters["execution_deadline_at"],
            }
        run.metadata_json = {**run.metadata_json, "upscale_run_id": child.id}
        append_event(
            session, run.id, "workflow.step.queued", {"run_id": child.id, "capability": child.capability}
        )

    def queue_video(self, session, run, artifact):
        from app.video import VideoRequest, create_video_run

        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        if (
            run.parameters.get("upscale_result")
            or run.parameters.get("mode") == "upscale"
            or run.metadata_json.get("video_run_id")
        ):
            raise ValueError("Invalid repeated image-to-video workflow dispatch")
        width, height = artifact.metadata_json["width"], artifact.metadata_json["height"]
        dimensions = (704, 1280) if height > width else (768, 768) if height == width else (1280, 704)
        child = create_video_run(
            session,
            VideoRequest(
                prompt=run.parameters["video_prompt"],
                image_artifact_id=artifact.id,
                width=dimensions[0],
                height=dimensions[1],
                gpu=run.requested_gpu,
            ),
            task=run.task,
            parent_run_id=run.id,
        )
        child.triggered_by = run.triggered_by
        run.metadata_json = {**run.metadata_json, "video_run_id": child.id}
        append_event(
            session, run.id, "workflow.step.queued", {"run_id": child.id, "capability": child.capability}
        )

    def _start(self, runner, run, allocated, output):
        if run.parameters.get("backend") == "krea2":
            model = run.parameters["image_model"]
            keys = (
                "mode",
                "width",
                "height",
                "steps",
                "cfg",
                "seed",
                "reference_strength",
                "reference_layout",
                "grounding_px",
                "negative",
            )
            options = {key: run.parameters[key] for key in keys if run.parameters.get(key) is not None}
            options["prompt"] = (
                run.parameters["edit_prompt"] if options["mode"] == "img2img" else run.parameters["prompt"]
            )
            return runner.start_krea_image(
                {
                    "run_id": run.id,
                    "options": options,
                    "model_file": model["model_file"],
                    "profile_sha256": model["profile_sha256"],
                    "gpus": [int(gpu) for gpu in run.allocated_resources["gpus"]],
                    "inputs": run.parameters.get("krea_inputs", []),
                    "permissions": ["filesystem_read", "workspace_write"],
                    **self.native_budget(run),
                }
            )
        payload = {
            key: run.parameters.get(key)
            for key in (
                "mode",
                "backend",
                "prompt",
                "negative",
                "edit_prompt",
                "width",
                "height",
                "steps",
                "cfg",
                "seed",
                "max_side",
                "repeats",
                "inputs",
            )
        }
        payload["prompt_style"] = run.parameters.get("prompt_style", "pipeline")
        if run.parameters.get("image_model"):
            payload["model_file"] = run.parameters["image_model"]["model_file"]
        payload.update(run_id=run.id, gpu=allocated, output_relative=output)
        payload.update(self.native_budget(run))
        return runner.start_photo(payload)
