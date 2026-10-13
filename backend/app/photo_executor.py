"""Adapter around the existing photo pipeline's typed Runner operation."""

from app.events import append_event
from app.host_media_executor import HostMediaExecutor
from app.permissions import require


class PhotoPipeExecutor(HostMediaExecutor):
    name = "photo_pipe"
    suffix = ".png"
    artifact_type = "image"
    mime_type = "image/png"

    def on_success(self, session, run, artifact):
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
        run.metadata_json = {**run.metadata_json, "upscale_run_id": child.id}
        append_event(
            session, run.id, "workflow.step.queued", {"run_id": child.id, "capability": child.capability}
        )

    def _start(self, runner, run, allocated, output):
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
        payload.update(run_id=run.id, gpu=allocated, output_relative=output)
        return runner.start_photo(payload)
